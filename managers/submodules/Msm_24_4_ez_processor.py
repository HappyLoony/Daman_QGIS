# -*- coding: utf-8 -*-
"""
Msm_24_4 - Обработка связей ЕЗ (Единое землепользование) с дочерними участками

Логика:
    1. Находит все выписки ЕЗ (Le_1_6_3_*)
    2. Извлекает список дочерних участков из поля "Обособленные_участки_ЕЗ"
       (working_name из Base_field_mapping_EGRN.json, unified_land_record)
    3. Находит эти участки в выборке (Le_2_1_1_1_Выборка_ЗУ)
    4. Проверяет что участки имеют тип "Обособленный участок" или "Условный участок"
    5. Проставляет поле "ЕЗ" = КН родительского ЕЗ
    6. Копирует сведения из ЕЗ в дочерние участки (всегда replace)
       ИСКЛЮЧЕНИЯ: не копируются Площадь и ВРИ (у каждого участка свои значения)

Запускается ПОСЛЕ основной синхронизации (Msm_24_3)

Перенесено из Fsm_2_2_4_ez_processor.py
"""

from typing import List, Dict, Optional, Any
from qgis.core import QgsVectorLayer, QgsFeature, QgsProject

from Daman_QGIS.utils import log_info, log_warning, log_success, log_error
from .Msm_24_0_sync_utils import values_differ, format_value_for_log


class Msm_24_4_EzProcessor:
    """Обработка связей ЕЗ с дочерними участками"""

    # Типы дочерних участков ЕЗ
    CHILD_TYPES = ["Обособленный участок", "Условный участок"]

    def __init__(self, iface, layer_manager, data_cleanup_manager=None):
        """
        Инициализация

        Args:
            iface: QGIS interface
            layer_manager: LayerManager экземпляр
            data_cleanup_manager: опциональный DataCleanupManager (Dependency Injection)
        """
        self.iface = iface
        self.layer_manager = layer_manager

        # Dependency Injection для DataCleanupManager
        if data_cleanup_manager is not None:
            self.data_cleanup_manager = data_cleanup_manager
        else:
            from Daman_QGIS.managers import DataCleanupManager
            self.data_cleanup_manager = DataCleanupManager()

    def process_ez_relations(self) -> Dict[str, int]:
        """
        Обработать все связи ЕЗ с дочерними участками

        Returns:
            dict: Статистика {'ez_count': int, 'children_updated': int, 'errors': int}
        """
        log_info("Msm_24_4: Начало обработки связей ЕЗ с дочерними участками")

        stats: Dict[str, int] = {
            'ez_count': 0,
            'children_updated': 0,
            'errors': 0
        }

        # ШАГ 1: Найти все слои выписок ЕЗ
        ez_layers = self._find_ez_vypiska_layers()
        if not ez_layers:
            log_info("Msm_24_4: Не найдены слои выписок ЕЗ (Le_1_6_3) - пропускаем")
            return stats

        # ШАГ 2: Найти слой выборки ЗУ
        selection_layer = self._find_selection_zu_layer()
        if selection_layer is None:
            log_warning("Msm_24_4: Не найден слой выборки Le_2_1_1_1_Выборка_ЗУ")
            return stats

        # ШАГ 3: Обработать каждый слой выписок ЕЗ
        for ez_layer in ez_layers:
            layer_stats = self._process_ez_layer(ez_layer, selection_layer)
            stats['ez_count'] += layer_stats['ez_count']
            stats['children_updated'] += layer_stats['children_updated']
            stats['errors'] += layer_stats['errors']

        if stats['ez_count'] > 0:
            log_success(
                f"Msm_24_4: Обработано {stats['ez_count']} ЕЗ, "
                f"обновлено {stats['children_updated']} дочерних участков, "
                f"ошибок: {stats['errors']}"
            )

        return stats

    def _find_ez_vypiska_layers(self) -> List[QgsVectorLayer]:
        """Найти все слои выписок ЕЗ"""
        ez_layers = []

        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and 'Le_1_6_3' in layer.name():
                if layer.isValid():
                    ez_layers.append(layer)
                    log_info(f"Msm_24_4: Найден слой выписок ЕЗ: {layer.name()}")
                else:
                    log_warning(f"Msm_24_4: Слой {layer.name()} невалидный")

        return ez_layers

    def _find_selection_zu_layer(self) -> Optional[QgsVectorLayer]:
        """Найти слой выборки ЗУ"""
        # Реальное название из Base_layers.json: Le_2_1_1_1_Выборка_ЗУ
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                # Ищем по полному имени или по вхождению
                if 'Le_2_1_1_1_Выборка_ЗУ' in layer.name() or layer.name() == 'Le_2_1_1_1_Выборка_ЗУ':
                    if layer.isValid():
                        log_info(f"Msm_24_4: Найден слой выборки: {layer.name()}")
                        return layer
                    else:
                        log_warning(f"Msm_24_4: Слой {layer.name()} невалидный")

        return None

    def _process_ez_layer(
        self,
        ez_layer: QgsVectorLayer,
        selection_layer: QgsVectorLayer
    ) -> Dict[str, int]:
        """
        Обработать один слой выписок ЕЗ

        Args:
            ez_layer: Слой выписок ЕЗ
            selection_layer: Слой выборки ЗУ

        Returns:
            dict: Статистика обработки
        """
        stats: Dict[str, int] = {'ez_count': 0, 'children_updated': 0, 'errors': 0}

        # Проверяем наличие необходимых полей
        if not self._validate_layers(ez_layer, selection_layer):
            return stats

        # Получаем индексы полей для выписки ЕЗ (working_name из Base_field_mapping_EGRN.json)
        ez_cadnum_idx = ez_layer.fields().indexOf('КН')
        ez_included_idx = ez_layer.fields().indexOf('Обособленные_участки_ЕЗ')

        # Получаем индексы полей для выборки
        sel_cadnum_idx = selection_layer.fields().indexOf('КН')
        sel_ez_idx = selection_layer.fields().indexOf('ЕЗ')
        sel_type_idx = selection_layer.fields().indexOf('Тип_объекта')

        # КРИТИЧЕСКИ ВАЖНО: перезагружаем ez_layer после Msm_24_3
        # После commitChanges() слой может оставаться в неконсистентном состоянии
        log_info(f"Msm_24_4: [{ez_layer.name()}] Перезагрузка слоя после Msm_24_3...")
        ez_layer.reload()
        log_info(f"Msm_24_4: [{ez_layer.name()}] Слой перезагружен, featureCount: {ez_layer.featureCount()}")

        # Читаем фичи из ez_layer ДО входа selection_layer в режим редактирования
        ez_features = list(ez_layer.getFeatures())
        log_info(f"Msm_24_4: [{ez_layer.name()}] Получено {len(ez_features)} фич для обработки")

        if not ez_features:
            log_info(f"Msm_24_4: [{ez_layer.name()}] Нет фич для обработки")
            return stats

        # Теперь можем войти в режим редактирования selection_layer
        selection_layer.startEditing()

        # Создаём индекс фич выборки по КН для быстрого поиска O(1) вместо O(n)
        selection_index: Dict[str, QgsFeature] = {}
        for feat in selection_layer.getFeatures():
            cadnum = feat[sel_cadnum_idx]
            if cadnum:
                selection_index[str(cadnum).strip()] = feat
        log_info(f"Msm_24_4: [{ez_layer.name()}] Создан индекс выборки: {len(selection_index)} объектов")

        for ez_feat in ez_features:
            ez_cadnum = ez_feat[ez_cadnum_idx]
            ez_included = ez_feat[ez_included_idx]

            if not ez_cadnum:
                log_warning("Msm_24_4: ЕЗ без кадастрового номера, пропускаем")
                stats['errors'] += 1
                continue

            if not ez_included or ez_included == '-':
                # ЕЗ без дочерних участков - это нормально, пропускаем
                continue

            # Парсим список дочерних КН
            child_cadnums = [cn.strip() for cn in str(ez_included).split(';') if cn.strip()]

            if not child_cadnums:
                # Пустой список после парсинга - пропускаем
                continue

            # Обрабатываем каждый дочерний участок
            ez_children_processed = 0
            for child_cadnum in child_cadnums:
                result = self._process_child_zu(
                    child_cadnum,
                    ez_cadnum,
                    ez_feat,
                    ez_layer,
                    selection_layer,
                    selection_index,
                    sel_ez_idx,
                    sel_type_idx
                )

                if result:
                    stats['children_updated'] += 1
                    ez_children_processed += 1

            # Логируем итоговую статистику по ЕЗ
            log_info(
                f"Msm_24_4: ЕЗ {ez_cadnum}: обработано {ez_children_processed} "
                f"из {len(child_cadnums)} дочерних участков "
                f"(остальные не попали в выборку или имеют неподходящий тип)"
            )

            stats['ez_count'] += 1

        # Сохраняем изменения
        if selection_layer.commitChanges():
            log_success(
                f"Msm_24_4: [{ez_layer.name()}] Сохранены изменения для "
                f"{stats['children_updated']} дочерних участков"
            )
        else:
            log_error(f"Msm_24_4: [{ez_layer.name()}] Ошибка сохранения изменений")
            errors = selection_layer.commitErrors()
            for error in errors:
                log_error(f"Msm_24_4: {error}")

        return stats

    def _validate_layers(
        self,
        ez_layer: QgsVectorLayer,
        selection_layer: QgsVectorLayer
    ) -> bool:
        """
        Проверить наличие необходимых полей в слоях

        После рефакторинга импорта (DATABASE-DRIVEN):
        - Поля используют working_name из Base_field_mapping_EGRN.json
        """
        # Проверяем поля в выписке ЕЗ (working_name из Base_field_mapping_EGRN.json)
        ez_required = ['КН', 'Обособленные_участки_ЕЗ']
        for field_name in ez_required:
            if ez_layer.fields().indexOf(field_name) == -1:
                log_error(
                    f"Msm_24_4: Слой {ez_layer.name()} не содержит поле '{field_name}'"
                )
                return False

        # Проверяем поля в выборке (working_name из Base_selection_ZU.json)
        sel_required = ['КН', 'ЕЗ', 'Тип_объекта']
        for field_name in sel_required:
            if selection_layer.fields().indexOf(field_name) == -1:
                log_error(
                    f"Msm_24_4: Слой {selection_layer.name()} не содержит поле '{field_name}'"
                )
                return False

        return True

    def _process_child_zu(
        self,
        child_cadnum: str,
        ez_cadnum: Any,
        ez_feat: QgsFeature,
        ez_layer: QgsVectorLayer,
        selection_layer: QgsVectorLayer,
        selection_index: Dict[str, QgsFeature],
        sel_ez_idx: int,
        sel_type_idx: int
    ) -> bool:
        """
        Обработать один дочерний участок

        Args:
            child_cadnum: КН дочернего участка
            ez_cadnum: КН родительского ЕЗ
            ez_feat: Фича ЕЗ (источник данных)
            ez_layer: Слой выписки ЕЗ
            selection_layer: Слой выборки
            selection_index: Индекс фич выборки по КН {cadnum: feature}
            sel_ez_idx: Индекс поля ЕЗ в выборке
            sel_type_idx: Индекс поля Тип_объекта в выборке

        Returns:
            bool: True если успешно обработан, False если ошибка
        """
        # Ищем дочерний участок в индексе выборки O(1)
        child_feat = selection_index.get(child_cadnum)

        if child_feat is None:
            # Участок не в выборке - это нормально, не все дочерние участки попадают в границы работ
            return False

        # Проверяем тип объекта
        child_type = child_feat[sel_type_idx]
        if child_type not in self.CHILD_TYPES:
            log_warning(
                f"Msm_24_4: Участок {child_cadnum} имеет тип '{child_type}', "
                f"ожидается {self.CHILD_TYPES}, пропускаем"
            )
            return False

        # Проставляем поле ЕЗ
        old_ez_value = child_feat[sel_ez_idx]
        if old_ez_value != ez_cadnum:
            selection_layer.changeAttributeValue(child_feat.id(), sel_ez_idx, ez_cadnum)
            log_info(
                f"Msm_24_4: {child_cadnum} | Поле 'ЕЗ': '{old_ez_value}' -> '{ez_cadnum}'"
            )

        # Копируем все сведения из ЕЗ в дочерний участок
        self._copy_ez_data_to_child(
            ez_feat,
            child_feat,
            ez_layer,
            selection_layer,
            child_cadnum,
            ez_cadnum
        )

        return True

    def _copy_ez_data_to_child(
        self,
        ez_feat: QgsFeature,
        child_feat: QgsFeature,
        ez_layer: QgsVectorLayer,
        selection_layer: QgsVectorLayer,
        child_cadnum: str,
        ez_cadnum: Any
    ) -> None:
        """
        Скопировать сведения из ЕЗ в дочерний участок

        Args:
            ez_feat: Фича ЕЗ (источник)
            child_feat: Фича дочернего участка (цель)
            ez_layer: Слой выписки ЕЗ
            selection_layer: Слой выборки
            child_cadnum: КН дочернего участка (для логирования)
            ez_cadnum: КН ЕЗ (для логирования)
        """
        # Маппинг полей: выписка ЕЗ -> выборка ЗУ (оба working_name)
        # Копируем все кроме КН, ЕЗ, Тип_объекта, Площади и ВРИ
        #
        # НЕ копируем:
        # - Тип_объекта - остаётся Обособленный/Условный
        # - Площадь - в ЕЗ общая площадь, у участков своя
        # - ВРИ - у каждого обособленного участка свой ВРИ
        #
        # После рефакторинга импорта (DATABASE-DRIVEN):
        # - Названия полей ИДЕНТИЧНЫ (маппинг 1:1)
        # - Собственники/Арендаторы уже в одном поле (conversion="semicolon_join")
        field_mappings = [
            'Адрес_Местоположения',
            'Категория',
            'Права',
            'Обременения',
            'Собственники',
            'Арендаторы',
            'Статус',
        ]

        for field_name in field_mappings:
            ez_field_idx = ez_layer.fields().indexOf(field_name)
            sel_field_idx = selection_layer.fields().indexOf(field_name)

            # Проверяем что поля существуют
            if ez_field_idx == -1 or sel_field_idx == -1:
                continue

            ez_value = ez_feat[ez_field_idx]
            child_value = child_feat[sel_field_idx]

            # Проверяем что значение отличается
            if values_differ(ez_value, child_value):
                # Санитизация значения перед записью (замена ; на / и т.д.)
                sanitized_value = (
                    self.data_cleanup_manager.sanitize_attribute_value(ez_value)
                    if isinstance(ez_value, str)
                    else ez_value
                )

                selection_layer.changeAttributeValue(child_feat.id(), sel_field_idx, sanitized_value)

                # Логируем изменение (показываем санитизированное значение - то, что РЕАЛЬНО записалось)
                old_val = format_value_for_log(child_value)
                new_val = format_value_for_log(sanitized_value)

                log_info(
                    f"Msm_24_4: {child_cadnum} (ЕЗ {ez_cadnum}) | "
                    f"'{field_name}': '{old_val}' -> '{new_val}'"
                )
