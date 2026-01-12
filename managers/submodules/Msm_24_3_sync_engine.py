# -*- coding: utf-8 -*-
"""
Msm_24_3 - Движок синхронизации данных с детальным логированием

Выполняет синхронизацию данных между слоями выписок и выборки
с подробным логированием всех изменений.

Логика:
    1. Для каждой пары слоёв находит совпадения по кадастровому номеру
    2. Для каждого совпадения сравнивает значения полей
    3. Применяет правило синхронизации (replace/fill)
    4. Логирует все изменения с указанием старого->нового значения

Перенесено из Fsm_2_2_3_sync_engine.py
"""

from typing import List, Tuple, Dict, Optional, Any
from qgis.core import QgsVectorLayer, QgsFeature

from Daman_QGIS.utils import log_info, log_warning, log_success
from .Msm_24_0_sync_utils import values_differ, is_empty, find_cadnum_field


class Msm_24_3_SyncEngine:
    """Движок синхронизации с логированием"""

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

    def sync_layers(
        self,
        layer_pairs: List[Tuple[QgsVectorLayer, QgsVectorLayer]],
        field_mappings: Dict[str, List[Tuple[str, str, str]]]
    ) -> Dict[str, Any]:
        """
        Выполнить синхронизацию всех пар слоёв

        Args:
            layer_pairs: Список пар (vypiska_layer, selection_layer)
            field_mappings: Маппинги полей для каждой пары

        Returns:
            dict: Статистика синхронизации
        """
        stats = {
            'total_features': 0,
            'matched_features': 0,
            'updated_features': 0,
            'fields_updated': 0,  # Заменённых полей
            'fields_filled': 0,   # Дополненных полей
        }

        for vypiska_layer, selection_layer in layer_pairs:
            pair_id = f"{vypiska_layer.name()}->{selection_layer.name()}"

            # Получаем маппинг для этой пары
            mappings = field_mappings.get(pair_id, [])
            if not mappings:
                log_warning(f"Msm_24_3: [{pair_id}] Нет маппинга полей, пропускаем")
                continue

            log_info(f"Msm_24_3: [{pair_id}] Начало синхронизации ({len(mappings)} полей)")

            # Синхронизируем эту пару
            pair_stats = self._sync_layer_pair(
                vypiska_layer,
                selection_layer,
                mappings,
                pair_id
            )

            # Обновляем общую статистику
            stats['total_features'] += pair_stats['total']
            stats['matched_features'] += pair_stats['matched']
            stats['updated_features'] += pair_stats['updated']
            stats['fields_updated'] += pair_stats['fields_replaced']
            stats['fields_filled'] += pair_stats['fields_filled']

            log_success(
                f"Msm_24_3: [{pair_id}] Обновлено {pair_stats['updated']} из {pair_stats['matched']} объектов "
                f"(замен: {pair_stats['fields_replaced']}, дополнений: {pair_stats['fields_filled']})"
            )

        return stats

    def _sync_layer_pair(
        self,
        vypiska_layer: QgsVectorLayer,
        selection_layer: QgsVectorLayer,
        field_mappings: List[Tuple[str, str, str]],
        pair_id: str
    ) -> Dict[str, int]:
        """
        Синхронизировать одну пару слоёв

        Args:
            vypiska_layer: Слой выписок (источник)
            selection_layer: Слой выборки (цель)
            field_mappings: [(vypiska_field, selection_field, priority), ...]
            pair_id: ID пары для логирования

        Returns:
            dict: Статистика синхронизации пары
        """
        stats = {
            'total': selection_layer.featureCount(),
            'matched': 0,
            'updated': 0,
            'fields_replaced': 0,
            'fields_filled': 0,
        }

        # Определяем поля кадастровых номеров
        vypiska_cadnum_field = find_cadnum_field(vypiska_layer)
        selection_cadnum_field = find_cadnum_field(selection_layer)

        if vypiska_cadnum_field is None or selection_cadnum_field is None:
            log_warning(f"Msm_24_3: [{pair_id}] Не найдено поле кадастрового номера")
            return stats

        # Создаём индекс выписок по кадастровому номеру
        vypiska_index: Dict[str, QgsFeature] = {}
        for feat in vypiska_layer.getFeatures():
            cadnum = feat[vypiska_cadnum_field]
            if cadnum:
                cadnum_clean = str(cadnum).strip()
                vypiska_index[cadnum_clean] = feat

        log_info(f"Msm_24_3: [{pair_id}] Индекс выписок: {len(vypiska_index)} кад. номеров")

        # Начинаем редактирование слоя выборки
        selection_layer.startEditing()

        # Проходим по всем фичам слоя выборки
        for selection_feat in selection_layer.getFeatures():
            cadnum = selection_feat[selection_cadnum_field]
            if not cadnum:
                continue

            cadnum_clean = str(cadnum).strip()

            # Ищем соответствующую фичу в выписках
            vypiska_feat = vypiska_index.get(cadnum_clean)
            if vypiska_feat is None:
                continue

            stats['matched'] += 1

            # Синхронизируем поля
            updated_fields = self._sync_feature_fields(
                vypiska_feat,
                selection_feat,
                selection_layer,
                field_mappings,
                cadnum_clean,
                pair_id
            )

            if updated_fields:
                stats['updated'] += 1
                stats['fields_replaced'] += updated_fields['replaced']
                stats['fields_filled'] += updated_fields['filled']

        # Сохраняем изменения
        if selection_layer.commitChanges():
            log_success(f"Msm_24_3: [{pair_id}] Изменения успешно сохранены")
        else:
            log_warning(f"Msm_24_3: [{pair_id}] Ошибка сохранения изменений")

        return stats

    def _sync_feature_fields(
        self,
        vypiska_feat: QgsFeature,
        selection_feat: QgsFeature,
        selection_layer: QgsVectorLayer,
        field_mappings: List[Tuple[str, str, str]],
        cadnum: str,
        pair_id: str
    ) -> Optional[Dict[str, int]]:
        """
        Синхронизировать поля одной фичи

        Args:
            vypiska_feat: Фича из выписки (источник)
            selection_feat: Фича из выборки (цель)
            selection_layer: Слой выборки
            field_mappings: Маппинги полей
            cadnum: Кадастровый номер для логирования
            pair_id: ID пары для логирования

        Returns:
            dict: {'replaced': int, 'filled': int} или None если не было изменений
        """
        changes = {'replaced': 0, 'filled': 0}
        has_changes = False

        for vypiska_field, selection_field, priority in field_mappings:
            vypiska_value = vypiska_feat[vypiska_field]
            selection_value = selection_feat[selection_field]

            # Проверяем нужно ли обновлять
            should_update = False

            if priority == 'replace':
                # Заменяем если значения различаются
                should_update = values_differ(vypiska_value, selection_value)

            elif priority == 'fill':
                # Дополняем только если поле пусто
                should_update = is_empty(selection_value) and not is_empty(vypiska_value)

            if should_update:
                # Санитизация значения перед записью (замена ; на / и т.д.)
                sanitized_value = (
                    self.data_cleanup_manager.sanitize_attribute_value(vypiska_value)
                    if isinstance(vypiska_value, str)
                    else vypiska_value
                )

                # Обновляем значение
                selection_layer.changeAttributeValue(
                    selection_feat.id(),
                    selection_layer.fields().indexOf(selection_field),
                    sanitized_value
                )

                if priority == 'replace':
                    changes['replaced'] += 1
                else:
                    changes['filled'] += 1

                has_changes = True

        return changes if has_changes else None
