# -*- coding: utf-8 -*-
"""
M_25_FillsManager - Менеджер распределения по категориям и правам

Назначение:
    Автоматическое распределение объектов из слоя выборки (Le_2_1_1_1_Выборка_ЗУ)
    по слоям категорий земель (L_2_2_*) и прав (L_2_3_*).

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
    - Msm_25_2_rights_classifier: классификация по правам
    - Msm_25_3_layer_distributor: распределение объектов по слоям
    - Msm_25_4_rights_dialog: GUI для ручной классификации
"""

from typing import Dict, List, Optional, Any
from qgis.core import QgsProject, QgsVectorLayer, QgsFeature

from Daman_QGIS.utils import log_info, log_warning, log_success, log_error
from Daman_QGIS.managers import get_reference_managers

from .submodules.Msm_25_3_layer_distributor import Msm_25_3_LayerDistributor
from .submodules.Msm_25_4_rights_dialog import show_rights_classification_dialog


class FillsManager:
    """
    Менеджер распределения по категориям и правам (Facade)

    Координирует работу субменеджеров для распределения объектов
    из слоя выборки в тематические слои.
    """

    # Имя исходного слоя выборки
    SOURCE_LAYER_NAME = "Le_2_1_1_1_Выборка_ЗУ"

    def __init__(self, iface, layer_manager=None):
        """
        Инициализация менеджера

        Args:
            iface: QGIS interface
            layer_manager: опциональный LayerManager
        """
        self.iface = iface
        self.layer_manager = layer_manager
        self._rights_layers_config: Optional[List[Dict]] = None

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
            result = distributor.distribute_by_rights(
                source_layer,
                unknown_handler=self._create_unknown_handler()
            )

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

    def _get_rights_layers_config(self) -> List[Dict]:
        """Получить конфигурацию слоёв прав из Base_layers.json"""
        if self._rights_layers_config is not None:
            return self._rights_layers_config

        ref_managers = get_reference_managers()
        layer_ref_manager = ref_managers.layer

        if not layer_ref_manager:
            log_warning("M_25: Не удалось получить layer reference manager")
            return []

        rights_layers = []
        all_layers = layer_ref_manager.get_base_layers()

        for layer_data in all_layers:
            group = layer_data.get('group', '')
            if group == 'Права':
                rights_layers.append(layer_data)

        self._rights_layers_config = rights_layers
        return rights_layers

    def _create_unknown_handler(self):
        """
        Создать handler для обработки неопознанных объектов

        Returns:
            Callable для передачи в distributor.distribute_by_rights()
        """
        rights_layers_config = self._get_rights_layers_config()

        def handler(feature: QgsFeature, index: int, total: int) -> Optional[str]:
            """
            Handler для неопознанных объектов

            Args:
                feature: Объект для классификации
                index: Текущий номер (1-based)
                total: Всего объектов

            Returns:
                str: имя слоя или "__SKIP_ALL__" или None
            """
            selected_layer, skip_all, accepted = show_rights_classification_dialog(
                parent=self.iface.mainWindow(),
                feature=feature,
                rights_layers=rights_layers_config,
                current_index=index,
                total_count=total
            )

            if skip_all:
                return "__SKIP_ALL__"
            if accepted and selected_layer:
                return selected_layer
            return None

        return handler

    def _perform_full_fill(self) -> Dict[str, Any]:
        """
        Выполнить полное распределение (внутренний метод)

        Returns:
            dict: статистика распределения
        """
        stats: Dict[str, Any] = {
            'categories': {},
            'rights': {}
        }

        source_layer = self._get_source_layer()
        if not source_layer:
            return stats

        # ШАГ 1: Распределение по категориям
        log_info("M_25: Шаг 1/2 - Распределение по категориям земель")
        distributor_cat = Msm_25_3_LayerDistributor(self.layer_manager)
        categories_result = distributor_cat.distribute_by_categories(source_layer)
        stats['categories'] = categories_result

        # ШАГ 2: Распределение по правам
        log_info("M_25: Шаг 2/2 - Распределение по правам")
        distributor_rights = Msm_25_3_LayerDistributor(self.layer_manager)
        rights_result = distributor_rights.distribute_by_rights(
            source_layer,
            unknown_handler=self._create_unknown_handler()
        )
        stats['rights'] = rights_result

        # Итоговое логирование
        cat_layers = len(categories_result.get('layers_created', []))
        rights_layers = len(rights_result.get('layers_created', []))
        log_success(
            f"M_25: Распределение завершено - "
            f"категории: {cat_layers} слоёв, права: {rights_layers} слоёв"
        )

        return stats


# Глобальный экземпляр (ленивая инициализация)
_fills_manager_instance: Optional[FillsManager] = None


def get_fills_manager(iface=None, layer_manager=None) -> FillsManager:
    """
    Получить глобальный экземпляр FillsManager

    Args:
        iface: QGIS interface (при первом вызове)
        layer_manager: LayerManager (опционально)

    Returns:
        FillsManager: глобальный экземпляр
    """
    global _fills_manager_instance

    if _fills_manager_instance is None:
        if iface is None:
            from qgis.utils import iface as qgis_iface
            iface = qgis_iface
        _fills_manager_instance = FillsManager(iface, layer_manager)
    elif layer_manager:
        _fills_manager_instance.set_layer_manager(layer_manager)

    return _fills_manager_instance


def reset_fills_manager() -> None:
    """
    Сброс глобального экземпляра FillsManager

    Используется при выгрузке плагина для освобождения ресурсов.
    """
    global _fills_manager_instance
    _fills_manager_instance = None
