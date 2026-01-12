# -*- coding: utf-8 -*-
"""
M_26_CuttingManager - Менеджер нарезки ЗПР

Назначение:
    Унифицированная нарезка зон планируемого размещения (ЗПР) по границам
    земельных участков и overlay слоёв.

Паттерн:
    Facade - единый интерфейс для нарезки всех типов ЗПР.

UI-точка входа:
    F_3_1 (единственная кнопка) -> cut_all() -> все типы ЗПР

Типы ЗПР:
    Стандартные:
        - ОКС: L_2_4_1_ЗПР_ОКС -> Le_3_1_1_*
        - ПО:  L_2_4_2_ЗПР_ПО  -> Le_3_1_2_*
        - ВО:  L_2_4_3_ЗПР_ВО  -> Le_3_1_3_*

    Рекреационные:
        - РЕК_АД:   L_2_5_1_ЗПР_РЕК_АД   -> Le_3_2_1_*
        - СЕТИ_ПО:  L_2_5_2_ЗПР_СЕТИ_ПО  -> Le_3_2_2_*
        - СЕТИ_ВО:  L_2_5_3_ЗПР_СЕТИ_ВО  -> Le_3_2_3_*
        - НЭ:       L_2_5_4_ЗПР_НЭ       -> Le_3_2_4_*

    Будущее:
        - Лесные выделы (планируется)

API:
    - cut_all() - нарезка ВСЕХ типов (вызывается из F_3_1)
    - cut_zpr() - нарезка стандартных ЗПР (ОКС, ЛО, ВО)
    - cut_zpr_rek() - нарезка рекреационных ЗПР_РЕК
    - check_data_availability() - проверка наличия данных

Субменеджеры:
    - Msm_26_1_geometry_processor: геометрические операции
    - Msm_26_2_attribute_mapper: маппинг атрибутов
    - Msm_26_3_layer_creator: создание слоёв в GPKG
    - Msm_26_4_cutting_engine: движок нарезки
    - Msm_26_5_kk_matcher: привязка НГС к кадастровым кварталам
    - Msm_26_6_point_creator: создание точечных слоёв
"""

from typing import Dict, List, Optional, Any, TYPE_CHECKING

from qgis.core import QgsProject, QgsVectorLayer

from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
from Daman_QGIS.constants import (
    # Слой границ нарезки
    LAYER_SELECTION_ZU,
    # Слой кадастровых кварталов
    LAYER_SELECTION_KK,
    # Стандартные ЗПР
    LAYER_ZPR_OKS, LAYER_ZPR_PO, LAYER_ZPR_VO,
    # Overlay слои
    LAYER_SELECTION_NP, LAYER_ATD_MO, LAYER_EGRN_LES, LAYER_SELECTION_VODA,
    # Выходные слои стандартных ЗПР
    LAYER_CUTTING_OKS_RAZDEL, LAYER_CUTTING_OKS_NGS,
    LAYER_CUTTING_PO_RAZDEL, LAYER_CUTTING_PO_NGS,
    LAYER_CUTTING_VO_RAZDEL, LAYER_CUTTING_VO_NGS,
)
from Daman_QGIS.managers import get_project_structure_manager
from Daman_QGIS.managers.M_28_layer_schema_validator import LayerSchemaValidator

if TYPE_CHECKING:
    from Daman_QGIS.managers import LayerManager


class CuttingManager:
    """
    Менеджер нарезки ЗПР (Facade)

    Координирует работу субменеджеров для нарезки зон планируемого
    размещения по границам земельных участков.
    """

    # Конфигурация стандартных ЗПР (F_3_1)
    ZPR_CONFIG = {
        'ОКС': {
            'source': LAYER_ZPR_OKS,
            'razdel': LAYER_CUTTING_OKS_RAZDEL,
            'ngs': LAYER_CUTTING_OKS_NGS,
            'points_razdel': 'Le_3_5_1_1_Т_Раздел_ЗПР_ОКС',
            'points_ngs': 'Le_3_5_1_2_Т_НГС_ЗПР_ОКС',
        },
        'ПО': {
            'source': LAYER_ZPR_PO,
            'razdel': LAYER_CUTTING_PO_RAZDEL,
            'ngs': LAYER_CUTTING_PO_NGS,
            'points_razdel': 'Le_3_5_2_1_Т_Раздел_ЗПР_ПО',
            'points_ngs': 'Le_3_5_2_2_Т_НГС_ЗПР_ПО',
        },
        'ВО': {
            'source': LAYER_ZPR_VO,
            'razdel': LAYER_CUTTING_VO_RAZDEL,
            'ngs': LAYER_CUTTING_VO_NGS,
            'points_razdel': 'Le_3_5_3_1_Т_Раздел_ЗПР_ВО',
            'points_ngs': 'Le_3_5_3_2_Т_НГС_ЗПР_ВО',
        },
    }

    # Конфигурация рекреационных ЗПР_РЕК (F_3_2)
    ZPR_REK_CONFIG = {
        'РЕК_АД': {
            'source': 'L_2_5_1_ЗПР_РЕК_АД',
            'razdel': 'Le_3_2_1_1_Раздел_ЗПР_РЕК_АД',
            'ngs': 'Le_3_2_1_2_НГС_ЗПР_РЕК_АД',
            'points_razdel': 'Le_3_6_1_1_Т_Раздел_ЗПР_РЕК_АД',
            'points_ngs': 'Le_3_6_1_2_Т_НГС_ЗПР_РЕК_АД',
        },
        'СЕТИ_ПО': {
            'source': 'L_2_5_2_ЗПР_СЕТИ_ПО',
            'razdel': 'Le_3_2_2_1_Раздел_ЗПР_СЕТИ_ПО',
            'ngs': 'Le_3_2_2_2_НГС_ЗПР_СЕТИ_ПО',
            'points_razdel': 'Le_3_6_2_1_Т_Раздел_ЗПР_СЕТИ_ПО',
            'points_ngs': 'Le_3_6_2_2_Т_НГС_ЗПР_СЕТИ_ПО',
        },
        'СЕТИ_ВО': {
            'source': 'L_2_5_3_ЗПР_СЕТИ_ВО',
            'razdel': 'Le_3_2_3_1_Раздел_ЗПР_СЕТИ_ВО',
            'ngs': 'Le_3_2_3_2_НГС_ЗПР_СЕТИ_ВО',
            'points_razdel': 'Le_3_6_3_1_Т_Раздел_ЗПР_СЕТИ_ВО',
            'points_ngs': 'Le_3_6_3_2_Т_НГС_ЗПР_СЕТИ_ВО',
        },
        'НЭ': {
            'source': 'L_2_5_4_ЗПР_НЭ',
            'razdel': 'Le_3_2_4_1_Раздел_ЗПР_НЭ',
            'ngs': 'Le_3_2_4_2_НГС_ЗПР_НЭ',
            'points_razdel': 'Le_3_6_4_1_Т_Раздел_ЗПР_НЭ',
            'points_ngs': 'Le_3_6_4_2_Т_НГС_ЗПР_НЭ',
        },
    }

    # Конфигурация overlay слоёв
    OVERLAY_CONFIG = {
        'НП': LAYER_SELECTION_NP,
        'МО': LAYER_ATD_MO,
        'Лес': LAYER_EGRN_LES,
        'Вода': LAYER_SELECTION_VODA,
    }

    def __init__(self, iface, layer_manager: 'LayerManager' = None):
        """
        Инициализация менеджера

        Args:
            iface: QGIS interface
            layer_manager: LayerManager для добавления слоёв
        """
        self.iface = iface
        self.layer_manager = layer_manager
        self.plugin_dir: Optional[str] = None
        self.project_manager = None

        # Субмодули (ленивая инициализация)
        self._geometry_processor = None
        self._attribute_mapper = None
        self._layer_creator = None
        self._cutting_engine = None

    def set_layer_manager(self, layer_manager: 'LayerManager') -> None:
        """Установить LayerManager"""
        self.layer_manager = layer_manager

    def set_plugin_dir(self, plugin_dir: str) -> None:
        """Установить путь к папке плагина"""
        self.plugin_dir = plugin_dir

    def set_project_manager(self, project_manager) -> None:
        """Установить ProjectManager"""
        self.project_manager = project_manager

    def check_data_availability(self, zpr_type: str = 'standard') -> Dict[str, Any]:
        """
        Проверить наличие данных для нарезки

        Args:
            zpr_type: 'standard' (ЗПР) или 'rek' (ЗПР_РЕК)

        Returns:
            dict: {
                'has_zu': bool - есть слой Выборка_ЗУ
                'zu_count': int - количество ЗУ
                'available_zpr': List[str] - доступные типы ЗПР
                'can_cut': bool - можно выполнить нарезку
            }
        """
        result = {
            'has_zu': False,
            'zu_count': 0,
            'available_zpr': [],
            'invalid_zpr': [],  # ЗПР с невалидной структурой
            'can_cut': False
        }

        # Проверка слоя ЗУ
        zu_layer = self._get_layer_by_name(LAYER_SELECTION_ZU)
        if zu_layer is not None and zu_layer.isValid() and zu_layer.featureCount() > 0:
            result['has_zu'] = True
            result['zu_count'] = zu_layer.featureCount()

        # Проверка слоёв ЗПР
        config = self.ZPR_CONFIG if zpr_type == 'standard' else self.ZPR_REK_CONFIG
        schema_validator = LayerSchemaValidator(self.plugin_dir)

        for zpr_name, zpr_config in config.items():
            layer = self._get_layer_by_name(zpr_config['source'])
            if layer is not None and layer.isValid() and layer.featureCount() > 0:
                # Валидация структуры ЗПР
                validation = schema_validator.validate_layer(layer, 'ZPR')
                if validation['valid']:
                    result['available_zpr'].append(zpr_name)
                else:
                    result['invalid_zpr'].append({
                        'name': zpr_name,
                        'layer': zpr_config['source'],
                        'missing_fields': validation['missing_fields']
                    })
                    log_warning(f"M_26: Слой {zpr_config['source']} имеет невалидную структуру, "
                               f"отсутствуют поля: {', '.join(validation['missing_fields'])}")

        result['can_cut'] = result['has_zu'] and len(result['available_zpr']) > 0

        return result

    def cut_zpr(self, zpr_types: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Нарезка стандартных ЗПР (ОКС, ЛО, ВО)

        Args:
            zpr_types: Список типов для нарезки. None = все доступные

        Returns:
            Dict: статистика нарезки
        """
        log_info("M_26: Начало нарезки стандартных ЗПР")

        availability = self.check_data_availability('standard')
        if not availability['can_cut']:
            log_warning("M_26: Нет данных для нарезки ЗПР")
            return {'error': 'Нет данных для нарезки'}

        # Определяем типы для обработки
        types_to_process = zpr_types or availability['available_zpr']
        types_to_process = [t for t in types_to_process if t in availability['available_zpr']]

        if not types_to_process:
            log_warning("M_26: Нет доступных типов ЗПР для нарезки")
            return {'error': 'Нет доступных типов ЗПР'}

        log_info(f"M_26: Будут обработаны типы: {types_to_process}")

        return self._perform_cutting(types_to_process, self.ZPR_CONFIG, 'standard')

    def cut_zpr_rek(self, zpr_types: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Нарезка рекреационных ЗПР_РЕК

        Args:
            zpr_types: Список типов для нарезки. None = все доступные

        Returns:
            Dict: статистика нарезки
        """
        log_info("M_26: Начало нарезки ЗПР_РЕК")

        availability = self.check_data_availability('rek')
        if not availability['can_cut']:
            log_warning("M_26: Нет данных для нарезки ЗПР_РЕК")
            return {'error': 'Нет данных для нарезки'}

        # Определяем типы для обработки
        types_to_process = zpr_types or availability['available_zpr']
        types_to_process = [t for t in types_to_process if t in availability['available_zpr']]

        if not types_to_process:
            log_warning("M_26: Нет доступных типов ЗПР_РЕК для нарезки")
            return {'error': 'Нет доступных типов ЗПР_РЕК'}

        log_info(f"M_26: Будут обработаны типы: {types_to_process}")

        return self._perform_cutting(types_to_process, self.ZPR_REK_CONFIG, 'rek')

    def cut_all(self) -> Dict[str, Any]:
        """
        Нарезка всех типов ЗПР и ЗПР_РЕК

        Returns:
            Dict: объединённая статистика
        """
        log_info("M_26: Начало полной нарезки (ЗПР + ЗПР_РЕК)")

        result = {
            'zpr': {},
            'zpr_rek': {},
            'total_razdel': 0,
            'total_ngs': 0
        }

        # Нарезка стандартных ЗПР
        zpr_result = self.cut_zpr()
        if 'error' not in zpr_result:
            result['zpr'] = zpr_result
            result['total_razdel'] += zpr_result.get('total_razdel', 0)
            result['total_ngs'] += zpr_result.get('total_ngs', 0)

        # Нарезка ЗПР_РЕК
        rek_result = self.cut_zpr_rek()
        if 'error' not in rek_result:
            result['zpr_rek'] = rek_result
            result['total_razdel'] += rek_result.get('total_razdel', 0)
            result['total_ngs'] += rek_result.get('total_ngs', 0)

        log_success(f"M_26: Полная нарезка завершена. "
                   f"Всего: {result['total_razdel']} Раздел, {result['total_ngs']} НГС")

        return result

    def _perform_cutting(
        self,
        zpr_types: List[str],
        config: Dict[str, Dict],
        mode: str
    ) -> Dict[str, Any]:
        """
        Выполнить нарезку указанных типов ЗПР

        Args:
            zpr_types: Список типов для обработки
            config: Конфигурация (ZPR_CONFIG или ZPR_REK_CONFIG)
            mode: 'standard' или 'rek'

        Returns:
            Dict: статистика нарезки
        """
        result = {
            'types_processed': [],
            'total_razdel': 0,
            'total_ngs': 0,
            'details': {}
        }

        # Инициализация субмодулей
        if not self._init_submodules():
            return {'error': 'Ошибка инициализации субмодулей'}

        # Получаем необходимые слои
        zu_layer = self._get_layer_by_name(LAYER_SELECTION_ZU)
        if zu_layer is None or not zu_layer.isValid():
            return {'error': 'Слой ЗУ не найден'}
        kk_layer = self._get_layer_by_name(LAYER_SELECTION_KK)
        overlay_layers = self._get_overlay_layers()
        crs = zu_layer.crs()

        # Сброс глобальных счётчиков КН/ЕЗ
        if self._cutting_engine:
            self._cutting_engine.attribute_mapper.reset_kn_counters()
            log_info("M_26: Сброс глобальных счётчиков КН/ЕЗ")

        # Обработка каждого типа ЗПР
        for zpr_type in zpr_types:
            zpr_config = config[zpr_type]
            zpr_layer = self._get_layer_by_name(zpr_config['source'])

            if zpr_layer is None or not zpr_layer.isValid():
                log_warning(f"M_26: Слой {zpr_config['source']} не найден, пропускаем")
                continue

            log_info(f"M_26: Обработка {zpr_type} ({zpr_layer.featureCount()} объектов)")

            # Выполняем нарезку через движок
            if self._cutting_engine is None:
                log_error("M_26: Движок нарезки не инициализирован")
                return {'error': 'Движок нарезки не инициализирован'}
            cut_result = self._cutting_engine.process_zpr_type(
                zpr_layer=zpr_layer,
                zu_layer=zu_layer,
                zpr_type=zpr_type,
                overlay_layers=overlay_layers,
                razdel_layer_name=zpr_config['razdel'],
                ngs_layer_name=zpr_config['ngs'],
                crs=crs,
                kk_layer=kk_layer
            )

            if cut_result:
                result['types_processed'].append(zpr_type)
                result['total_razdel'] += cut_result.get('razdel_count', 0)
                result['total_ngs'] += cut_result.get('ngs_count', 0)
                result['details'][zpr_type] = cut_result

                # Добавляем слои в проект
                self._add_result_layers(cut_result)

                log_info(f"M_26: {zpr_type} - создано {cut_result.get('razdel_count', 0)} Раздел, "
                        f"{cut_result.get('ngs_count', 0)} НГС")

                # Валидация минимальных площадей для типа ЗПР
                self._validate_min_areas(zpr_type)

        # Сортировка слоёв
        if self.layer_manager and result['types_processed']:
            self.layer_manager.sort_all_layers()
            log_info("M_26: Слои отсортированы")

        log_success(f"M_26: Нарезка {mode} завершена. "
                   f"Всего: {result['total_razdel']} Раздел, {result['total_ngs']} НГС")

        return result

    def _init_submodules(self) -> bool:
        """
        Инициализация субмодулей

        Returns:
            bool: True если успешно
        """
        try:
            if not self.plugin_dir:
                log_error("M_26: plugin_dir не установлен")
                return False

            gpkg_path = self._get_gpkg_path()
            if not gpkg_path:
                log_error("M_26: Не удалось получить путь к GeoPackage")
                return False

            # Импорт субмодулей Msm_26_*
            from Daman_QGIS.managers.submodules.Msm_26_1_geometry_processor import Msm_26_1_GeometryProcessor
            from Daman_QGIS.managers.submodules.Msm_26_2_attribute_mapper import Msm_26_2_AttributeMapper
            from Daman_QGIS.managers.submodules.Msm_26_3_layer_creator import Msm_26_3_LayerCreator
            from Daman_QGIS.managers.submodules.Msm_26_4_cutting_engine import Msm_26_4_CuttingEngine

            self._geometry_processor = Msm_26_1_GeometryProcessor()
            self._attribute_mapper = Msm_26_2_AttributeMapper(self.plugin_dir)
            self._layer_creator = Msm_26_3_LayerCreator(gpkg_path, self._attribute_mapper)
            self._cutting_engine = Msm_26_4_CuttingEngine(
                geometry_processor=self._geometry_processor,
                attribute_mapper=self._attribute_mapper,
                layer_creator=self._layer_creator
            )

            log_info("M_26: Субмодули инициализированы")
            return True

        except Exception as e:
            log_error(f"M_26: Ошибка инициализации субмодулей: {e}")
            import traceback
            log_error(traceback.format_exc())
            return False

    def _get_gpkg_path(self) -> Optional[str]:
        """Получить путь к GeoPackage проекта"""
        if not self.project_manager or not self.project_manager.current_project:
            return None

        structure_manager = get_project_structure_manager()
        structure_manager.project_root = self.project_manager.current_project
        return structure_manager.get_gpkg_path(create=False)

    def _get_layer_by_name(self, layer_name: str) -> Optional[QgsVectorLayer]:
        """Получить слой по имени из проекта"""
        layers = QgsProject.instance().mapLayersByName(layer_name)
        if layers:
            layer = layers[0]
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                return layer
        return None

    def _get_overlay_layers(self) -> Dict[str, QgsVectorLayer]:
        """Получить доступные overlay слои"""
        overlay_layers = {}
        for overlay_type, layer_name in self.OVERLAY_CONFIG.items():
            layer = self._get_layer_by_name(layer_name)
            if layer is not None and layer.isValid() and layer.featureCount() > 0:
                overlay_layers[overlay_type] = layer
                log_info(f"M_26: Найден overlay слой {layer_name}")
        return overlay_layers

    def _add_result_layers(self, cut_result: Dict[str, Any]) -> None:
        """Добавить результирующие слои в проект"""
        if not self.layer_manager:
            return

        # Полигональные слои
        for layer_key in ['razdel_layer', 'ngs_layer']:
            layer = cut_result.get(layer_key)
            if layer:
                self.layer_manager.add_layer(
                    layer, make_readonly=False, auto_number=False, check_precision=False
                )

        # Точечные слои
        for layer_key in ['razdel_points_layer', 'ngs_points_layer']:
            layer = cut_result.get(layer_key)
            if layer:
                self.layer_manager.add_layer(
                    layer, make_readonly=False, auto_number=False, check_precision=False
                )

    def _validate_min_areas(self, zpr_type: str) -> None:
        """Валидация минимальных площадей для типа ЗПР

        Args:
            zpr_type: Тип ЗПР (ОКС, ЛО, ВО, РЕК_АД и т.д.)
        """
        try:
            from Daman_QGIS.managers import MinAreaValidator

            validator = MinAreaValidator(self.plugin_dir)
            result = validator.validate_cutting_results(zpr_type, show_dialog=True)

            if result.get('skipped_no_field'):
                log_info(f"M_26: Валидация {zpr_type} пропущена (нет поля MIN_AREA_VRI)")
            elif result.get('success'):
                log_info(f"M_26: Валидация {zpr_type} успешна")
            else:
                log_warning(
                    f"M_26: Валидация {zpr_type} - найдено {result.get('problem_count', 0)} "
                    f"контуров с недостаточной площадью"
                )
        except Exception as e:
            log_error(f"M_26: Ошибка валидации минимальных площадей: {e}")


# Глобальный экземпляр (ленивая инициализация)
_cutting_manager_instance: Optional[CuttingManager] = None


def get_cutting_manager(iface=None, layer_manager=None) -> CuttingManager:
    """
    Получить глобальный экземпляр CuttingManager

    Args:
        iface: QGIS interface (при первом вызове)
        layer_manager: LayerManager (опционально)

    Returns:
        CuttingManager: глобальный экземпляр
    """
    global _cutting_manager_instance

    if _cutting_manager_instance is None:
        if iface is None:
            from qgis.utils import iface as qgis_iface
            iface = qgis_iface
        _cutting_manager_instance = CuttingManager(iface, layer_manager)
    elif layer_manager:
        _cutting_manager_instance.set_layer_manager(layer_manager)

    return _cutting_manager_instance


def reset_cutting_manager() -> None:
    """Сбросить глобальный экземпляр"""
    global _cutting_manager_instance
    _cutting_manager_instance = None
