# -*- coding: utf-8 -*-
"""
Fsm_1_2_10: AsyncTask для загрузки Web карт

Наследует от BaseAsyncTask (M_17) для унифицированной обработки.
Выполняет загрузку данных в background thread, добавление слоёв в main thread.

ARCHITECTURE:
- execute(): Загрузка данных через API, сохранение в GPKG (background thread)
- on_completed callback: Добавление слоёв в проект, применение стилей (main thread)

IMPORTANT:
- Передаём layer_id, НЕ layer object
- Все операции с QgsProject/GUI только через callback в main thread
- Loaders (EGRN, FGISLK, OSM) используют requests (thread-safe)
"""

import os
import tempfile
import shutil
from typing import Any, Optional, Dict, List, Tuple, TYPE_CHECKING
from concurrent.futures import ThreadPoolExecutor, as_completed

from qgis.core import QgsProject, QgsVectorLayer, QgsRasterLayer

from Daman_QGIS.managers.submodules.Msm_17_1_base_task import BaseAsyncTask
from Daman_QGIS.managers import APIManager, DataCleanupManager
from Daman_QGIS.utils import log_info, log_error, log_warning, log_success

if TYPE_CHECKING:
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_0_layer_config_builder import Fsm_1_2_0_LayerConfigBuilder
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_1_egrn_loader import Fsm_1_2_1_EgrnLoader
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_5_atd_loader import Fsm_1_2_5_AtdLoader
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_7_parent_layer_manager import Fsm_1_2_7_ParentLayerManager
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_8_geometry_processor import Fsm_1_2_8_GeometryProcessor
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_9_zouit_loader import Fsm_1_2_9_ZouitLoader


class Fsm_1_2_10_WebMapLoadTask(BaseAsyncTask):
    """
    Task для асинхронной загрузки Web карт.

    Выполняет в background thread:
    - Загрузка ЕГРН слоёв через API NSPD
    - Загрузка ФГИС ЛК слоёв
    - Загрузка OSM слоёв через QuickOSM
    - Загрузка ЗОУИТ слоёв
    - Подготовка WMS слоёв

    Результат передаётся в on_completed callback для добавления слоёв в main thread.

    Usage:
        from Daman_QGIS.managers import get_async_manager

        task = Fsm_1_2_10_WebMapLoadTask(
            boundary_layer_id=boundary_layer.id(),
            gpkg_path=gpkg_path,
            iface=iface,
            project_manager=project_manager,
            layer_manager=layer_manager
        )
        manager = get_async_manager(iface)
        manager.run(task, on_completed=handle_layers_addition)
    """

    def __init__(self,
                 boundary_layer_id: str,
                 gpkg_path: str,
                 iface,
                 project_manager,
                 layer_manager,
                 load_groups: Optional[List[str]] = None):
        """
        Args:
            boundary_layer_id: ID слоя границ работ (L_1_1_2_Границы_работ_10_м)
            gpkg_path: Путь к GeoPackage проекта
            iface: QgisInterface
            project_manager: ProjectManager instance
            layer_manager: LayerManager instance
            load_groups: Список групп для загрузки (None = все)
                         ['egrn', 'fgislk', 'osm', 'zouit', 'wms']
        """
        super().__init__("Загрузка Web карт", can_cancel=True)

        self.boundary_layer_id = boundary_layer_id
        self.gpkg_path = gpkg_path
        self.iface = iface
        self.project_manager = project_manager
        self.layer_manager = layer_manager
        self.load_groups = load_groups or ['egrn', 'fgislk', 'osm', 'zouit', 'wms']

        # Инициализируем менеджеры
        self.api_manager: Optional[APIManager] = None
        self.data_cleanup_manager = DataCleanupManager()

        # Loaders (lazy init в execute, типизированы для Pylance)
        self.config_builder: Optional['Fsm_1_2_0_LayerConfigBuilder'] = None
        self.egrn_loader: Optional['Fsm_1_2_1_EgrnLoader'] = None
        self.quickosm_loader = None  # Не используется в background thread
        self.geometry_processor: Optional['Fsm_1_2_8_GeometryProcessor'] = None
        self.atd_loader: Optional['Fsm_1_2_5_AtdLoader'] = None
        self.raster_loader = None  # Не используется в background thread
        self.parent_layer_manager: Optional['Fsm_1_2_7_ParentLayerManager'] = None
        self.zouit_loader: Optional['Fsm_1_2_9_ZouitLoader'] = None

        # Результаты для передачи в main thread
        self.loaded_layer_names: List[str] = []
        self.statistics: Dict[str, int] = {}
        self.errors: List[str] = []

    def execute(self) -> Dict[str, Any]:
        """
        Основная логика загрузки Web карт в background thread.

        Returns:
            dict: Результаты загрузки с ключами:
                - loaded_layer_names: список имён загруженных слоёв (для загрузки из GPKG)
                - statistics: статистика по группам
                - errors: список ошибок
                - gpkg_path: путь к GeoPackage
        """
        # Получаем слой границ по ID
        boundary_layer = QgsProject.instance().mapLayer(self.boundary_layer_id)
        if not boundary_layer:
            raise ValueError(f"Слой границ не найден (id={self.boundary_layer_id})")

        results = {
            'loaded_layer_names': [],
            'statistics': {
                'egrn': 0,
                'fgislk': 0,
                'osm': 0,
                'zouit': 0,
                'wms': 0
            },
            'errors': [],
            'gpkg_path': self.gpkg_path
        }

        # Инициализация
        self.report_progress(2, "Инициализация компонентов...")
        self._init_components()

        if self.is_cancelled():
            return results

        total_groups = len(self.load_groups)

        # Загружаем каждую группу
        for idx, group in enumerate(self.load_groups):
            if self.is_cancelled():
                log_warning("Fsm_1_2_10: Загрузка отменена пользователем")
                results['errors'].append("Загрузка отменена пользователем")
                return results

            # Обновляем прогресс
            base_progress = int(5 + (idx / total_groups) * 90)
            self.report_progress(base_progress, f"Загрузка {group}...")

            try:
                if group == 'egrn':
                    count, layer_names = self._load_egrn_data(boundary_layer)
                    results['statistics']['egrn'] = count
                    results['loaded_layer_names'].extend(layer_names)

                elif group == 'fgislk':
                    count, layer_names = self._load_fgislk_data(boundary_layer)
                    results['statistics']['fgislk'] = count
                    results['loaded_layer_names'].extend(layer_names)

                elif group == 'osm':
                    count, layer_names = self._load_osm_data(boundary_layer)
                    results['statistics']['osm'] = count
                    results['loaded_layer_names'].extend(layer_names)

                elif group == 'zouit':
                    count, layer_names = self._load_zouit_data(boundary_layer)
                    results['statistics']['zouit'] = count
                    results['loaded_layer_names'].extend(layer_names)

                elif group == 'wms':
                    # WMS слои добавляются в main thread (растровые)
                    results['statistics']['wms'] = 3  # Google, NSPD, ЦОС

            except Exception as e:
                error_msg = f"Ошибка загрузки группы {group}: {str(e)}"
                log_error(f"Fsm_1_2_10: {error_msg}")
                results['errors'].append(error_msg)

        self.report_progress(100, "Загрузка данных завершена")

        return results

    def _init_components(self):
        """Инициализация компонентов загрузки (lazy imports)"""

        # APIManager
        if not self.api_manager:
            self.api_manager = APIManager()

        # Config builder
        if not self.config_builder:
            from .Fsm_1_2_0_layer_config_builder import Fsm_1_2_0_LayerConfigBuilder
            self.config_builder = Fsm_1_2_0_LayerConfigBuilder(self.api_manager)

        # EGRN loader
        if not self.egrn_loader:
            from .Fsm_1_2_1_egrn_loader import Fsm_1_2_1_EgrnLoader
            self.egrn_loader = Fsm_1_2_1_EgrnLoader(self.iface, self.api_manager)

        # Geometry processor
        if not self.geometry_processor:
            from .Fsm_1_2_8_geometry_processor import Fsm_1_2_8_GeometryProcessor
            self.geometry_processor = Fsm_1_2_8_GeometryProcessor(self.iface)

        # ATD loader
        if not self.atd_loader:
            from .Fsm_1_2_5_atd_loader import Fsm_1_2_5_AtdLoader
            self.atd_loader = Fsm_1_2_5_AtdLoader(self.iface, self.egrn_loader, self.api_manager)

        # Parent layer manager
        if not self.parent_layer_manager:
            from .Fsm_1_2_7_parent_layer_manager import Fsm_1_2_7_ParentLayerManager
            self.parent_layer_manager = Fsm_1_2_7_ParentLayerManager(self.iface, self.layer_manager)

        # ZOUIT loader
        if not self.zouit_loader:
            from .Fsm_1_2_9_zouit_loader import Fsm_1_2_9_ZouitLoader
            self.zouit_loader = Fsm_1_2_9_ZouitLoader(
                self.iface, self.egrn_loader, self.layer_manager,
                self.geometry_processor, self.api_manager
            )

    def _load_egrn_data(self, boundary_layer) -> Tuple[int, List[str]]:
        """
        Загрузка данных ЕГРН через API NSPD.

        Returns:
            Tuple[int, List[str]]: (количество загруженных, список имён слоёв)
        """
        # Type assertions для Pylance (гарантировано после _init_components)
        assert self.config_builder is not None
        assert self.api_manager is not None
        assert self.atd_loader is not None
        assert self.egrn_loader is not None
        assert self.geometry_processor is not None

        loaded_layer_names = []
        loaded_count = 0

        try:
            # Получаем конфигурацию слоёв
            layers_config = self.config_builder.get_layers_config_from_database()

            # Извлекаем АТД слои для параллельной загрузки
            atd_configs = [cfg for cfg in layers_config
                          if cfg['enabled'] and isinstance(cfg.get('category_id'), dict)]

            atd_results = {}

            if atd_configs:
                # Параллельная загрузка АТД слоёв
                first_atd_endpoint = self.api_manager.get_endpoint_by_layer(atd_configs[0]['layer_name'])
                if first_atd_endpoint:
                    atd_max_workers = first_atd_endpoint.get('max_workers', 3)

                    with ThreadPoolExecutor(max_workers=atd_max_workers) as executor:
                        futures = {
                            executor.submit(self.atd_loader.load_single_atd_layer, config, None): config['layer_name']
                            for config in atd_configs
                        }

                        for future in as_completed(futures):
                            if self.is_cancelled():
                                executor.shutdown(wait=False, cancel_futures=True)
                                return loaded_count, loaded_layer_names

                            try:
                                result = future.result(timeout=180)
                                layer_name = result['config']['layer_name']
                                atd_results[layer_name] = result
                            except Exception as e:
                                layer_name = futures[future]
                                log_error(f"Fsm_1_2_10: Ошибка загрузки АТД {layer_name}: {str(e)}")

            # Обработка всех слоёв
            for config in layers_config:
                if not config['enabled']:
                    continue

                if self.is_cancelled():
                    break

                try:
                    layer_name = config['layer_name']

                    # АТД слои (используем предзагруженные данные)
                    if isinstance(config['category_id'], dict):
                        if layer_name not in atd_results:
                            continue

                        result = atd_results[layer_name]
                        layer = result.get('layer')
                        feature_count = result.get('feature_count', 0)

                        if not layer or feature_count == 0:
                            continue

                    # ОКС - объединённая загрузка
                    elif config['category_id'] == 'oks_combined':
                        geometry_provider = self.egrn_loader.get_boundary_extent
                        layer, feature_count = self.egrn_loader.load_oks_combined(
                            layer_name=config['layer_name'],
                            geometry_provider=geometry_provider,
                            progress_task=None
                        )

                    # ЗОУИТ - пропускаем (отдельная группа)
                    elif config['category_id'] == 'zouit_layers':
                        continue

                    # Остальные слои
                    else:
                        boundary_selector = self.api_manager.get_boundary_layer_name(layer_name)
                        if boundary_selector == "L_1_1_3_Границы_работ_500_м":
                            egrn_loader = self.egrn_loader
                            geometry_provider = lambda: egrn_loader.get_boundary_extent(use_500m_buffer=True)
                        else:
                            geometry_provider = self.egrn_loader.get_boundary_extent

                        layer, feature_count = self.egrn_loader.load_layer(
                            layer_name=config['layer_name'],
                            geometry_provider=geometry_provider,
                            progress_task=None
                        )

                    # Сохраняем в GeoPackage
                    if layer and feature_count > 0:
                        clean_name = self.data_cleanup_manager.sanitize_filename(config['layer_name'])
                        layer.setName(clean_name)

                        saved_layer = self.geometry_processor.save_to_geopackage(
                            layer, self.gpkg_path, clean_name
                        )
                        if saved_layer:
                            loaded_layer_names.append(clean_name)
                            loaded_count += 1

                except Exception as e:
                    log_error(f"Fsm_1_2_10: Ошибка загрузки {config['layer_name']}: {str(e)}")

        except Exception as e:
            log_error(f"Fsm_1_2_10: Критическая ошибка загрузки ЕГРН: {str(e)}")

        return loaded_count, loaded_layer_names

    def _load_fgislk_data(self, boundary_layer) -> Tuple[int, List[str]]:
        """
        Загрузка данных ФГИС ЛК.

        Returns:
            Tuple[int, List[str]]: (количество загруженных, список имён слоёв)
        """
        # Type assertions для Pylance (гарантировано после _init_components)
        assert self.api_manager is not None
        assert self.geometry_processor is not None

        loaded_layer_names = []
        loaded_count = 0

        try:
            from .Fsm_1_2_4_fgislk_loader import Fsm_1_2_4_FgislkLoader

            fgislk_loader = Fsm_1_2_4_FgislkLoader(self.iface, self.api_manager)

            # Временная директория для тайлов
            temp_dir = tempfile.mkdtemp(prefix="fgislk_")

            try:
                fgislk_layers = fgislk_loader.load_layers(temp_dir)

                if fgislk_layers:
                    for layer_name, layer in fgislk_layers.items():
                        if self.is_cancelled():
                            break

                        try:
                            # Сохраняем в GeoPackage
                            saved_layer = self.geometry_processor.save_to_geopackage(
                                layer, self.gpkg_path, layer_name
                            )
                            if saved_layer and "_ФГИС_ЛК_СРАВНИ_С_ЕГРН" not in layer_name:
                                loaded_layer_names.append(layer_name)
                                loaded_count += 1
                        except Exception as e:
                            log_error(f"Fsm_1_2_10: Ошибка сохранения ФГИС ЛК {layer_name}: {str(e)}")

            finally:
                # Очистка временной директории
                try:
                    shutil.rmtree(temp_dir)
                except OSError:
                    pass

        except Exception as e:
            log_error(f"Fsm_1_2_10: Ошибка загрузки ФГИС ЛК: {str(e)}")

        return loaded_count, loaded_layer_names

    def _load_osm_data(self, boundary_layer) -> Tuple[int, List[str]]:
        """
        Загрузка данных OSM через QuickOSM.

        NOTE: OSM загружается в main thread через _load_main_thread_layers()
        Этот метод только возвращает 0 для статистики в background thread.

        Returns:
            Tuple[int, List[str]]: (0, []) - реальная загрузка в main thread
        """
        # OSM требует main thread (QuickOSM использует QgsProject напрямую)
        # Загрузка выполняется в F_1_2._load_main_thread_layers()
        return 0, []

    def _load_zouit_data(self, boundary_layer) -> Tuple[int, List[str]]:
        """
        Загрузка данных ЗОУИТ.

        NOTE: ЗОУИТ загружается в main thread через _load_main_thread_layers()
        Этот метод только возвращает 0 для статистики в background thread.

        Returns:
            Tuple[int, List[str]]: (0, []) - реальная загрузка в main thread
        """
        # ЗОУИТ требует main thread (сложная логика с QgsProject)
        # Загрузка выполняется в F_1_2._load_main_thread_layers()
        return 0, []
