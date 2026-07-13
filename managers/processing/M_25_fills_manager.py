# -*- coding: utf-8 -*-
"""
M_25_FillsManager - Менеджер распределения по категориям и правам

Назначение:
    Автоматическое распределение объектов из слоя выборки (Le_1_9_1_1_Выборка_ЗУ)
    по слоям категорий земель (L_1_10_*) и прав (L_1_11_*).

Паттерн:
    Facade - предоставляет упрощённый интерфейс к подсистеме из 5 субменеджеров.

Сценарии вызова:
    - F_1_1 (после импорта и синхронизации) - автоматически
    - F_2_3 (ручной запуск) - по запросу пользователя

API:
    - auto_fill() - автоматическое распределение (категории + права)
    - fill_categories() - только категории
    - fill_rights() - только права
    - check_data_availability() - проверка наличия данных

Субменеджеры:
    - Msm_25_0_fills_utils: утилиты (создание слоя, сохранение в GPKG)
    - Msm_25_1_category_classifier: классификация по категориям
    - Msm_25_2_rights_classifier: классификация по правам (читает __Форма_тех)
    - Msm_25_3_layer_distributor: распределение объектов по слоям

Классификация прав (Вариант B, §5.5):
    Классификатор читает ТРАНЗИТНОЕ поле формы (__Форма_тех), а не "Собственники"
    (та = имя правообладателя). Непознанное (промах формы ИЛИ права) уходит ТИХО
    в L_1_11_6_Свед_нет — интерактивный диалог Msm_25_4 удалён (решение владельца
    2026-07-12): маппинг стабилен, ручной разбор — по ревью слоя Свед_нет владельцем.
"""

from typing import Dict, List, Optional, Any
from qgis.core import QgsProject, QgsVectorLayer

from Daman_QGIS.constants import LAYER_SELECTION_ZU
from Daman_QGIS.utils import log_info, log_warning, log_success, log_error

from .submodules.Msm_25_3_layer_distributor import Msm_25_3_LayerDistributor

# Lazy import для избежания циклических зависимостей
# get_reference_managers импортируется внутри методов
# ПРИМЕЧАНИЕ: интерактивный диалог классификации (Msm_25_4) выведен из потока
# (§5.5, решение владельца 2026-07-12) — всё непознанное тихо -> Свед_нет.

__all__ = ['FillsManager']


class FillsManager:
    """
    Менеджер распределения по категориям и правам (Facade)

    Координирует работу субменеджеров для распределения объектов
    из слоя выборки в тематические слои.
    """

    # Имя исходного слоя выборки
    SOURCE_LAYER_NAME = LAYER_SELECTION_ZU

    def __init__(self, iface, layer_manager=None):
        """
        Инициализация менеджера

        Args:
            iface: QGIS interface
            layer_manager: опциональный LayerManager
        """
        self.iface = iface
        self.layer_manager = layer_manager

    def set_layer_manager(self, layer_manager) -> None:
        """
        Установить LayerManager

        Args:
            layer_manager: экземпляр LayerManager
        """
        self.layer_manager = layer_manager

    def check_data_availability(self) -> Dict[str, Any]:
        """
        Проверить наличие данных для распределения

        Returns:
            dict: {
                'has_source': bool,        # Есть слой выборки
                'source_count': int,       # Количество объектов в выборке
                'can_fill': bool           # Можно выполнить распределение
            }
        """
        project = QgsProject.instance()
        source_layer = project.mapLayersByName(self.SOURCE_LAYER_NAME)

        if source_layer and isinstance(source_layer[0], QgsVectorLayer):
            has_source = source_layer[0].featureCount() > 0
            source_count = source_layer[0].featureCount()
        else:
            has_source = False
            source_count = 0

        return {
            'has_source': has_source,
            'source_count': source_count,
            'can_fill': has_source
        }

    def auto_fill(self) -> Dict[str, Any]:
        """
        Автоматическое распределение (категории + права)

        Проверяет наличие данных и выполняет распределение.
        Если данных нет - возвращает пустой результат без ошибок.

        Returns:
            dict: статистика распределения или пустой dict
        """
        log_info("M_25: Начало авторасспределения (категории + права)")

        # Проверяем наличие данных
        availability = self.check_data_availability()

        if not availability['can_fill']:
            log_info("M_25: Нет данных для распределения - пропускаем")
            return {}

        log_info(f"M_25: Найдено {availability['source_count']} объектов для распределения")

        try:
            return self._perform_full_fill()
        except Exception as e:
            log_error(f"M_25: Ошибка распределения: {e}")
            import traceback
            log_error(traceback.format_exc())
            return {'error': str(e)}

    def fill_categories(self) -> Dict[str, Any]:
        """
        Распределение только по категориям земель

        Returns:
            dict: статистика распределения по категориям
        """
        log_info("M_25: Распределение по категориям земель")

        availability = self.check_data_availability()
        if not availability['can_fill']:
            log_info("M_25: Нет данных для распределения по категориям")
            return {}

        try:
            source_layer = self._get_source_layer()
            if not source_layer:
                return {}

            distributor = Msm_25_3_LayerDistributor(self.layer_manager)
            result = distributor.distribute_by_categories(source_layer)

            if result.get('success'):
                log_success(f"M_25: Категории - создано {len(result.get('layers_created', []))} слоёв")

            return result

        except Exception as e:
            log_error(f"M_25: Ошибка распределения по категориям: {e}")
            return {'error': str(e)}

    def fill_rights(self) -> Dict[str, Any]:
        """
        Распределение только по правам

        Returns:
            dict: статистика распределения по правам
        """
        log_info("M_25: Распределение по правам")

        availability = self.check_data_availability()
        if not availability['can_fill']:
            log_info("M_25: Нет данных для распределения по правам")
            return {}

        try:
            source_layer = self._get_source_layer()
            if not source_layer:
                return {}

            distributor = Msm_25_3_LayerDistributor(self.layer_manager)
            result = distributor.distribute_by_rights(source_layer)

            if result.get('success'):
                log_success(f"M_25: Права - создано {len(result.get('layers_created', []))} слоёв")

            return result

        except Exception as e:
            log_error(f"M_25: Ошибка распределения по правам: {e}")
            return {'error': str(e)}

    def _get_source_layer(self) -> Optional[QgsVectorLayer]:
        """Получить исходный слой выборки"""
        project = QgsProject.instance()
        source_layers = project.mapLayersByName(self.SOURCE_LAYER_NAME)
        if source_layers and isinstance(source_layers[0], QgsVectorLayer):
            return source_layers[0]
        log_warning(f"M_25: Слой {self.SOURCE_LAYER_NAME} не найден")
        return None

    def _cleanup_existing_fills(self) -> int:
        """
        Удалить существующие слои заливки (L_1_10_* и L_1_11_*) перед пересозданием

        Обеспечивает идемпотентность: при повторном запуске старые слои
        удаляются и создаются заново с актуальными данными.

        Returns:
            int: Количество удалённых слоёв
        """
        project = QgsProject.instance()
        removed_count = 0

        # Паттерны слоёв заливки
        fill_prefixes = ('L_1_10_', 'L_1_11_')

        layers_to_remove = []
        for layer in project.mapLayers().values():
            layer_name = layer.name()
            if any(layer_name.startswith(prefix) for prefix in fill_prefixes):
                layers_to_remove.append(layer)

        for layer in layers_to_remove:
            layer_name = layer.name()
            project.removeMapLayer(layer.id())
            removed_count += 1
            log_info(f"M_25: Удалён старый слой заливки: {layer_name}")

        if removed_count > 0:
            log_info(f"M_25: Очищено {removed_count} существующих слоёв заливки")

        return removed_count

    def _perform_full_fill(self) -> Dict[str, Any]:
        """
        Выполнить полное распределение (внутренний метод)

        Returns:
            dict: статистика распределения
        """
        stats: Dict[str, Any] = {
            'categories': {},
            'rights': {},
            'cleaned_layers': 0
        }

        source_layer = self._get_source_layer()
        if not source_layer:
            return stats

        # ШАГ 0: Очистка существующих слоёв заливки
        stats['cleaned_layers'] = self._cleanup_existing_fills()

        # ШАГ 1: Распределение по категориям
        log_info("M_25: Шаг 1/2 - Распределение по категориям земель")
        distributor_cat = Msm_25_3_LayerDistributor(self.layer_manager)
        categories_result = distributor_cat.distribute_by_categories(source_layer)
        stats['categories'] = categories_result

        # ШАГ 2: Распределение по правам
        log_info("M_25: Шаг 2/2 - Распределение по правам")
        distributor_rights = Msm_25_3_LayerDistributor(self.layer_manager)
        rights_result = distributor_rights.distribute_by_rights(source_layer)
        stats['rights'] = rights_result

        # Итоговое логирование
        cat_layers = len(categories_result.get('layers_created', []))
        rights_layers = len(rights_result.get('layers_created', []))
        log_success(
            f"M_25: Распределение завершено - "
            f"категории: {cat_layers} слоёв, права: {rights_layers} слоёв"
        )

        return stats
