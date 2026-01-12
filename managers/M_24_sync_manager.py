# -*- coding: utf-8 -*-
"""
M_24_SyncManager - Менеджер синхронизации выписок с выборкой

Назначение:
    Автоматическая синхронизация данных из слоёв выписок ЕГРН (Le_1_6_*)
    в слои выборки (L_2_1_*).

Паттерн:
    Facade - предоставляет упрощённый интерфейс к подсистеме из 5 субменеджеров.

Сценарии вызова:
    - F_1_1 (после импорта выписок) - автоматически

API:
    - auto_sync() - автоматическая синхронизация (без диалогов)
    - check_data_availability() - проверка наличия данных

Субменеджеры:
    - Msm_24_0_sync_utils: утилиты сравнения значений
    - Msm_24_1_layer_matcher: поиск пар слоёв
    - Msm_24_2_field_mapper: маппинг полей
    - Msm_24_3_sync_engine: движок синхронизации
    - Msm_24_4_ez_processor: обработка связей ЕЗ
"""

from typing import Dict, List, Optional, Any
from qgis.core import QgsProject, QgsVectorLayer

from Daman_QGIS.utils import log_info, log_warning, log_success, log_error

from .submodules.Msm_24_1_layer_matcher import Msm_24_1_LayerMatcher
from .submodules.Msm_24_2_field_mapper import Msm_24_2_FieldMapper
from .submodules.Msm_24_3_sync_engine import Msm_24_3_SyncEngine
from .submodules.Msm_24_4_ez_processor import Msm_24_4_EzProcessor


class SyncManager:
    """
    Менеджер синхронизации выписок с выборкой (Facade)

    Координирует работу субменеджеров для синхронизации данных
    из выписок ЕГРН в слои выборки.
    """

    def __init__(self, iface, data_cleanup_manager=None):
        """
        Инициализация менеджера

        Args:
            iface: QGIS interface
            data_cleanup_manager: опциональный DataCleanupManager (Dependency Injection)
        """
        self.iface = iface
        self.layer_manager = None
        self._data_cleanup_manager = data_cleanup_manager

    def set_layer_manager(self, layer_manager) -> None:
        """
        Установить LayerManager

        Args:
            layer_manager: экземпляр LayerManager
        """
        self.layer_manager = layer_manager

    def check_data_availability(self) -> Dict[str, Any]:
        """
        Проверить наличие данных для синхронизации

        Returns:
            dict: {
                'has_vypiski': bool,      # Есть слои выписок Le_1_6_*
                'has_selection': bool,    # Есть слои выборки L_2_1_*
                'can_sync': bool,         # Можно выполнить синхронизацию
                'vypiska_count': int,     # Количество слоёв выписок
                'selection_count': int    # Количество слоёв выборки
            }
        """
        project = QgsProject.instance()
        all_layers = project.mapLayers().values()

        # Слои выписок (Le_1_6_1, Le_1_6_2, Le_1_6_3 - без Le_1_6_4 ЧЗУ)
        vypiska_layers = [
            layer for layer in all_layers
            if isinstance(layer, QgsVectorLayer)
            and layer.name().startswith('Le_1_6_')
            and not layer.name().startswith('Le_1_6_4')  # ЧЗУ не участвуют
        ]

        # Слои выборки (L_2_1_* и Le_2_1_*)
        selection_layers = [
            layer for layer in all_layers
            if isinstance(layer, QgsVectorLayer)
            and (layer.name().startswith('L_2_1_') or layer.name().startswith('Le_2_1_'))
        ]

        has_vypiski = len(vypiska_layers) > 0
        has_selection = len(selection_layers) > 0

        return {
            'has_vypiski': has_vypiski,
            'has_selection': has_selection,
            'can_sync': has_vypiski and has_selection,
            'vypiska_count': len(vypiska_layers),
            'selection_count': len(selection_layers)
        }

    def auto_sync(self) -> Dict[str, Any]:
        """
        Автоматическая синхронизация (без диалогов)

        Проверяет наличие данных и выполняет синхронизацию.
        Если данных нет - возвращает пустой результат без ошибок.

        Returns:
            dict: статистика синхронизации или пустой dict если нечего синхронизировать
        """
        log_info("M_24: Начало автосинхронизации выписок -> выборка")

        # Проверяем наличие данных
        availability = self.check_data_availability()

        if not availability['can_sync']:
            if not availability['has_vypiski']:
                log_info("M_24: Нет слоёв выписок - синхронизация не требуется")
            if not availability['has_selection']:
                log_info("M_24: Нет слоёв выборки - синхронизация не требуется")
            return {}

        log_info(
            f"M_24: Найдено {availability['vypiska_count']} слоёв выписок, "
            f"{availability['selection_count']} слоёв выборки"
        )

        try:
            return self._perform_sync()
        except Exception as e:
            log_error(f"M_24: Ошибка синхронизации: {e}")
            import traceback
            log_error(traceback.format_exc())
            return {'error': str(e)}

    def _perform_sync(self) -> Dict[str, Any]:
        """
        Выполнить синхронизацию (внутренний метод)

        Returns:
            dict: статистика синхронизации
        """
        stats: Dict[str, Any] = {
            'total_features': 0,
            'matched_features': 0,
            'updated_features': 0,
            'fields_updated': 0,
            'fields_filled': 0,
            'ez_count': 0,
            'ez_children_updated': 0,
            'ez_errors': 0
        }

        # ШАГ 1: Поиск пар слоёв
        log_info("M_24: Шаг 1/3 - Поиск пар слоёв (выписки -> выборка)")
        matcher = Msm_24_1_LayerMatcher()
        layer_pairs = matcher.find_layer_pairs()

        if not layer_pairs:
            log_warning("M_24: Не найдено пар слоёв для синхронизации")
            return stats

        log_success(f"M_24: Найдено {len(layer_pairs)} пар слоёв")

        # ШАГ 2: Создание маппинга полей
        log_info("M_24: Шаг 2/3 - Создание маппинга полей")
        mapper = Msm_24_2_FieldMapper()
        field_mappings = mapper.create_field_mappings(layer_pairs)

        total_fields = sum(len(m) for m in field_mappings.values())
        log_success(f"M_24: Создан маппинг для {total_fields} полей")

        # ШАГ 3: Выполнение синхронизации
        log_info("M_24: Шаг 3/3 - Синхронизация данных")
        engine = Msm_24_3_SyncEngine(
            self.iface,
            self.layer_manager,
            data_cleanup_manager=self._data_cleanup_manager
        )
        sync_stats = engine.sync_layers(layer_pairs, field_mappings)

        # Обновляем статистику
        stats['total_features'] = sync_stats.get('total_features', 0)
        stats['matched_features'] = sync_stats.get('matched_features', 0)
        stats['updated_features'] = sync_stats.get('updated_features', 0)
        stats['fields_updated'] = sync_stats.get('fields_updated', 0)
        stats['fields_filled'] = sync_stats.get('fields_filled', 0)

        # ШАГ 4: Обработка связей ЕЗ
        log_info("M_24: Шаг 4/4 - Обработка связей ЕЗ с дочерними участками")
        ez_processor = Msm_24_4_EzProcessor(
            self.iface,
            self.layer_manager,
            data_cleanup_manager=self._data_cleanup_manager
        )
        ez_stats = ez_processor.process_ez_relations()

        stats['ez_count'] = ez_stats.get('ez_count', 0)
        stats['ez_children_updated'] = ez_stats.get('children_updated', 0)
        stats['ez_errors'] = ez_stats.get('errors', 0)

        # Итоговое логирование
        log_success(
            f"M_24: Синхронизация завершена - "
            f"обновлено {stats['updated_features']} объектов, "
            f"заменено {stats['fields_updated']} полей, "
            f"дополнено {stats['fields_filled']} полей"
        )

        if stats['ez_count'] > 0:
            log_success(
                f"M_24: Обработано {stats['ez_count']} ЕЗ, "
                f"обновлено {stats['ez_children_updated']} дочерних участков"
            )

        return stats
