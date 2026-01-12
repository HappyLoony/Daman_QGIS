# -*- coding: utf-8 -*-
"""
Msm_13_3: Field Cleanup - Очистка полей

Удаление пустых полей из слоёв:
- Проверка пустоты полей
- Удаление пустых полей из слоя
- Пакетная очистка нескольких слоёв
- Статистика очистки
"""

from typing import List, Dict, Optional, Any
from qgis.core import QgsVectorLayer, QgsField
from Daman_QGIS.utils import log_info, log_warning, log_debug


class FieldCleanup:
    """
    Менеджер для удаления полностью пустых полей из векторных слоёв

    Удаляет поля, которые пустые во ВСЕХ объектах слоя.
    Используется после импорта данных (например, из XML выписок ЕГРН).

    Примеры использования:
        >>> cleanup = FieldCleanup()
        >>> stats = cleanup.remove_empty_fields(layer)
        >>> # или для нескольких слоёв:
        >>> batch_stats = cleanup.cleanup_layers_batch([layer1, layer2, layer3])
    """

    def __init__(self, log_details: bool = True):
        """
        Инициализация менеджера очистки полей

        Args:
            log_details: Логировать детальную информацию об удалённых полях
        """
        self.log_details = log_details

    def is_field_empty(self, layer: QgsVectorLayer, field_name: str) -> bool:
        """
        Проверяет, пустое ли поле во ВСЕХ объектах слоя

        Поле считается пустым, если во всех записях:
        - Значение NULL
        - Или пустая строка ("")
        - Или строка из пробелов

        Args:
            layer: Векторный слой QGIS
            field_name: Имя поля для проверки

        Returns:
            True если поле пустое во всех записях, иначе False
        """
        if layer is None or not layer.isValid():
            return False

        field_idx = layer.fields().lookupField(field_name)
        if field_idx == -1:
            return False

        # Проверяем все объекты
        for feature in layer.getFeatures():
            value = feature.attribute(field_idx)

            # Если хотя бы одно значение НЕ пустое - поле не пустое
            if value is not None:
                value_str = str(value).strip()
                if value_str and value_str != "NULL":
                    return False

        return True

    def get_empty_fields(self, layer: QgsVectorLayer) -> List[str]:
        """
        Получает список всех пустых полей в слое

        Args:
            layer: Векторный слой QGIS

        Returns:
            Список имён полей, которые пусты во всех записях
        """
        if layer is None or not layer.isValid():
            return []

        empty_fields = []
        for field in layer.fields():
            if self.is_field_empty(layer, field.name()):
                empty_fields.append(field.name())

        return empty_fields

    def remove_empty_fields(
        self,
        layer: QgsVectorLayer,
        exclude_fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Удаляет все пустые поля из слоя

        Args:
            layer: Векторный слой QGIS
            exclude_fields: Список полей, которые НЕ удалять (например, fid, geometry)

        Returns:
            Словарь со статистикой:
            {
                'layer_name': str,
                'total_fields': int,
                'removed_fields': List[str],
                'removed_count': int,
                'remaining_fields': int
            }
        """
        if layer is None or not layer.isValid():
            log_warning("Msm_13_3_FieldCleanup: Слой недействителен или не существует")
            return {
                'layer_name': None,
                'total_fields': 0,
                'removed_fields': [],
                'removed_count': 0,
                'remaining_fields': 0
            }

        layer_name = layer.name()
        total_fields = layer.fields().count()

        # Поля, которые нельзя удалять по умолчанию
        default_exclude = ['fid', 'id', 'ogc_fid']
        exclude_set = set(default_exclude)
        if exclude_fields:
            exclude_set.update(exclude_fields)

        # Находим пустые поля
        empty_fields = []
        for field in layer.fields():
            field_name = field.name()
            if field_name not in exclude_set and self.is_field_empty(layer, field_name):
                empty_fields.append(field_name)

        # Удаляем пустые поля
        if empty_fields:
            field_indices = [layer.fields().lookupField(fn) for fn in empty_fields]

            # Начинаем редактирование
            layer.startEditing()

            # Удаляем атрибуты
            success = layer.dataProvider().deleteAttributes(field_indices)

            if success:
                layer.updateFields()
                layer.commitChanges()

                # Логируем
                if self.log_details:
                    log_info(f"Msm_13_3_FieldCleanup: Слой '{layer_name}': удалено {len(empty_fields)} пустых полей")
                    for field_name in empty_fields:
                        log_debug(f"Msm_13_3_FieldCleanup:   - {field_name}")
            else:
                layer.rollBack()
                log_warning(f"Msm_13_3_FieldCleanup: Слой '{layer_name}': не удалось удалить пустые поля")

        remaining_fields = layer.fields().count()

        return {
            'layer_name': layer_name,
            'total_fields': total_fields,
            'removed_fields': empty_fields,
            'removed_count': len(empty_fields),
            'remaining_fields': remaining_fields
        }

    def cleanup_layers_batch(
        self,
        layers: List[QgsVectorLayer],
        exclude_fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Очистка пустых полей для нескольких слоёв

        Args:
            layers: Список векторных слоёв QGIS
            exclude_fields: Поля, которые не удалять

        Returns:
            Общая статистика:
            {
                'total_layers': int,
                'total_fields_removed': int,
                'layers_stats': List[Dict]
            }
        """
        layers_stats = []
        total_removed = 0

        for layer in layers:
            if layer is not None and layer.isValid():
                stats = self.remove_empty_fields(layer, exclude_fields)
                layers_stats.append(stats)
                total_removed += stats['removed_count']

        log_info(
            f"Msm_13_3_FieldCleanup: Очистка завершена: обработано {len(layers_stats)} слоёв, "
            f"удалено {total_removed} пустых полей"
        )

        return {
            'total_layers': len(layers_stats),
            'total_fields_removed': total_removed,
            'layers_stats': layers_stats
        }

    def get_cleanup_summary(self, stats: Dict[str, Any]) -> str:
        """
        Формирует текстовую сводку по очистке для отображения пользователю

        Args:
            stats: Статистика от cleanup_layers_batch() или remove_empty_fields()

        Returns:
            Форматированная строка со статистикой
        """
        if 'total_layers' in stats:
            # Это статистика batch
            summary_lines = [
                f"Очистка пустых полей завершена:",
                f"  Обработано слоёв: {stats['total_layers']}",
                f"  Удалено полей: {stats['total_fields_removed']}",
                ""
            ]

            if stats['layers_stats']:
                summary_lines.append("Детали по слоям:")
                for layer_stat in stats['layers_stats']:
                    if layer_stat['removed_count'] > 0:
                        summary_lines.append(
                            f"  • {layer_stat['layer_name']}: "
                            f"удалено {layer_stat['removed_count']} из {layer_stat['total_fields']} полей"
                        )
                        if self.log_details and layer_stat['removed_fields']:
                            for field_name in layer_stat['removed_fields'][:5]:  # Первые 5
                                summary_lines.append(f"      - {field_name}")
                            if len(layer_stat['removed_fields']) > 5:
                                summary_lines.append(f"      ... и ещё {len(layer_stat['removed_fields']) - 5}")
        else:
            # Это статистика для одного слоя
            summary_lines = [
                f"Слой '{stats['layer_name']}':",
                f"  Всего полей: {stats['total_fields']}",
                f"  Удалено: {stats['removed_count']}",
                f"  Осталось: {stats['remaining_fields']}"
            ]

            if self.log_details and stats['removed_fields']:
                summary_lines.append("  Удалённые поля:")
                for field_name in stats['removed_fields']:
                    summary_lines.append(f"    - {field_name}")

        return "\n".join(summary_lines)
