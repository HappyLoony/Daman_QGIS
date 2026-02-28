# -*- coding: utf-8 -*-
"""
Инструмент F_1_2_Загрузка Web карт
Загрузка Web слоев с помощью внешних модулей okno_egrn и okno_fgislk

Использует async режим (M_17): Фоновая обработка через QgsTask, не блокирует UI.
"""

import os
from typing import Optional, Dict, Any, Tuple, List, TYPE_CHECKING

from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    QgsProject, Qgis, QgsVectorLayer, QgsRasterLayer,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsRectangle,
    QgsPointXY
)

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.managers import LayerManager, APIManager, DataCleanupManager, registry
from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
from Daman_QGIS.constants import (
    DEFAULT_LAYER_ORDER, WMS_GOOGLE_SATELLITE, NSPD_TILE_URL,
    LAYER_GOOGLE_SATELLITE, LAYER_NSPD_BASE, PROVIDER_OGR, DRIVER_GPKG,
    PROVIDER_WMS, PLUGIN_NAME
)

# Async Task для M_17 (новая реализация)
from .submodules.Fsm_1_2_10_web_map_task import Fsm_1_2_10_WebMapLoadTask

# Импорты субмодулей перенесены внутрь run() для lazy loading
# Это предотвращает краш QGIS при загрузке плагина

if TYPE_CHECKING:
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_0_layer_config_builder import Fsm_1_2_0_LayerConfigBuilder
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_1_egrn_loader import Fsm_1_2_1_EgrnLoader
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_3_quickosm_loader import Fsm_1_2_3_QuickOSMLoader
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_5_atd_loader import Fsm_1_2_5_AtdLoader
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_6_raster_loader import Fsm_1_2_6_RasterLoader
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_7_parent_layer_manager import Fsm_1_2_7_ParentLayerManager
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_8_geometry_processor import Fsm_1_2_8_GeometryProcessor
    from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_9_zouit_loader import Fsm_1_2_9_ZouitLoader



class F_1_2_LoadWMS(BaseTool):
    """Инструмент загрузки Web слоев

    Использует async режим (M_17): Фоновая обработка через QgsTask, не блокирует UI.
    ЕГРН и ФГИС ЛК загружаются в background thread,
    OSM, ЗОУИТ и WMS загружаются в main thread callback.
    """

    def __init__(self, iface) -> None:
        """Инициализация инструмента"""
        super().__init__(iface)
        self.project_manager = None
        self.layer_manager: Optional[LayerManager] = None
        self.replacement_manager = None
        self.api_manager: Optional[APIManager] = None  # APIManager для работы с endpoints
        self.data_cleanup_manager = DataCleanupManager()
        self.egrn_loader: Optional['Fsm_1_2_1_EgrnLoader'] = None
        self.quickosm_loader: Optional['Fsm_1_2_3_QuickOSMLoader'] = None

        # Async manager (M_17)
        self.async_manager = None

        # Субмодули (lazy initialization в run())
        self.config_builder: Optional['Fsm_1_2_0_LayerConfigBuilder'] = None
        self.geometry_processor: Optional['Fsm_1_2_8_GeometryProcessor'] = None
        self.atd_loader: Optional['Fsm_1_2_5_AtdLoader'] = None
        self.raster_loader: Optional['Fsm_1_2_6_RasterLoader'] = None
        self.parent_layer_manager: Optional['Fsm_1_2_7_ParentLayerManager'] = None
        self.zouit_loader: Optional['Fsm_1_2_9_ZouitLoader'] = None
        self.redline_loader = None  # Fsm_1_2_11_RedlineLoader (lazy init)
        self.servitude_loader = None  # Fsm_1_2_14_ServitudeLoader (lazy init)

    def set_project_manager(self, project_manager) -> None:
        """Установка менеджера проектов"""
        self.project_manager = project_manager

    def set_layer_manager(self, layer_manager) -> None:
        """Установка менеджера слоев"""
        self.layer_manager = layer_manager
        self.replacement_manager = layer_manager.replacement_manager if layer_manager else None

    def get_name(self) -> str:
        """Получить имя инструмента"""
        return "F_1_2_Загрузка Web карт"

    def run(self) -> None:
        """Основной метод запуска инструмента через M_17 AsyncTaskManager"""
        # Проверяем что проект открыт
        if not self.project_manager or not self.project_manager.project_db:
            QMessageBox.critical(
                None,
                "Ошибка",
                "Проект не открыт!\n\n"
                "Откройте или создайте проект через инструменты F_0_1 или F_0_2."
            )
            return

        # Проверяем наличие слоя границ работ с буфером 10м
        project = QgsProject.instance()
        boundary_layer = None

        for layer in project.mapLayers().values():
            if layer.name() == "L_1_1_2_Границы_работ_10_м":
                boundary_layer = layer
                break

        if not boundary_layer or not boundary_layer.isValid():
            QMessageBox.critical(
                None,
                "Ошибка",
                "Слой L_1_1_2_Границы_работ_10_м не найден!\n\n"
                "Создайте слой границ работ с буфером 10м перед загрузкой Web слоев."
            )
            return

        # Проверяем что CRS boundary слоя даёт адекватные координаты в WGS-84
        if not self._validate_boundary_crs(boundary_layer):
            return

        # Пре-диалог авторизации НСПД
        from .submodules.Fsm_1_2_12_auth_pre_dialog import Fsm_1_2_12_AuthPreDialog
        from qgis.PyQt.QtWidgets import QDialog

        pre_dialog = Fsm_1_2_12_AuthPreDialog(self.iface.mainWindow())
        if pre_dialog.exec() != QDialog.Accepted:
            return  # Пользователь отменил

        # Автоматическая очистка слоёв
        self.auto_cleanup_layers()

        # Инициализируем async manager
        if self.async_manager is None:
            self.async_manager = registry.get('M_17')

        # Type assertion для Pylance (проверено в run() перед вызовом)
        assert self.project_manager is not None
        assert self.project_manager.project_db is not None

        # Получаем путь к GeoPackage
        gpkg_path = self.project_manager.project_db.gpkg_path

        # Создаём task (передаём layer_id, НЕ layer!)
        task = Fsm_1_2_10_WebMapLoadTask(
            boundary_layer_id=boundary_layer.id(),
            gpkg_path=gpkg_path,
            iface=self.iface,
            project_manager=self.project_manager,
            layer_manager=self.layer_manager
        )

        # Запускаем через AsyncTaskManager
        self.async_manager.run(
            task,
            show_progress=True,
            on_completed=self._on_load_completed,
            on_failed=self._on_load_failed,
            on_cancelled=self._on_load_cancelled
        )

    def _validate_boundary_crs(self, boundary_layer: QgsVectorLayer) -> bool:
        """Проверка что CRS boundary слоя трансформируется в WGS-84 с адекватными координатами.

        Трансформирует центр extent в EPSG:4326 и проверяет что результат
        попадает в допустимые пределы (lon: -180..180, lat: -90..90).
        Защита от запуска F_1_2 до корректной настройки CRS через F_0_3.

        Returns:
            True если CRS корректна, False если нет (показывает диалог ошибки)
        """
        try:
            layer_crs = boundary_layer.crs()
            if not layer_crs.isValid():
                QMessageBox.critical(
                    None,
                    "Ошибка CRS",
                    "Система координат слоя границ работ не определена.\n\n"
                    "Укажите CRS через F_0_3 (Свойства проекта) перед загрузкой Web карт."
                )
                return False

            extent = boundary_layer.extent()
            if extent.isEmpty():
                return True  # Пустой extent - пропускаем проверку

            center = extent.center()
            wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')

            if layer_crs != wgs84:
                transform = QgsCoordinateTransform(layer_crs, wgs84, QgsProject.instance())
                center_wgs84 = transform.transform(QgsPointXY(center.x(), center.y()))
            else:
                center_wgs84 = QgsPointXY(center.x(), center.y())

            lon = center_wgs84.x()
            lat = center_wgs84.y()

            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                log_warning(
                    f"F_1_2: CRS проверка не пройдена - центр boundary в WGS-84: "
                    f"lon={lon:.4f}, lat={lat:.4f} (вне допустимых пределов)"
                )
                QMessageBox.critical(
                    None,
                    "Ошибка CRS",
                    f"Система координат слоя границ работ некорректна.\n\n"
                    f"Центр территории в WGS-84: lon={lon:.1f}, lat={lat:.1f}\n"
                    f"(ожидается lon: -180..180, lat: -90..90)\n\n"
                    f"Укажите корректную CRS через F_0_3 (Свойства проекта)."
                )
                return False

            return True

        except Exception as e:
            log_warning(f"F_1_2: Не удалось проверить CRS boundary слоя: {e}")
            # При ошибке трансформации - не блокируем, но предупреждаем
            return True

    def _on_load_completed(self, result: Dict[str, Any]) -> None:
        """Callback при успешном завершении загрузки (main thread)"""

        statistics = result.get('statistics', {})
        loaded_layer_names = result.get('loaded_layer_names', [])
        errors = result.get('errors', [])
        gpkg_path = result.get('gpkg_path', '')

        # Добавляем загруженные слои из GPKG в проект
        self._add_layers_from_gpkg(loaded_layer_names, gpkg_path)

        # Загружаем ЗОУИТ и WMS слои (требуют main thread)
        # OSM теперь загружается в background thread через Fsm_1_2_10
        main_thread_stats = self._load_main_thread_layers()

        # Финальная сортировка
        if self.layer_manager:
            self.layer_manager.sort_all_layers()

        # Автоматическая выборка ЗУ/ОКС (F_2_1)
        selection_stats = self._auto_run_selection()

        # Собираем финальную статистику
        egrn = statistics.get('egrn', 0)
        fgislk = statistics.get('fgislk', 0)
        osm = statistics.get('osm', 0)  # OSM теперь из background thread
        zouit = main_thread_stats.get('zouit', 0)
        redline = main_thread_stats.get('redline', 0)
        servitude = main_thread_stats.get('servitude', 0)
        wms = main_thread_stats.get('wms', 0)

        selection_layers = selection_stats.get('selection_layers', 0) if selection_stats else 0

        message = f"Загрузка завершена! ЕГРН: {egrn}, ФГИС ЛК: {fgislk}, OSM: {osm}, ЗОУИТ: {zouit}, КЛ: {redline}, ПС: {servitude}, WMS: {wms}"
        if selection_layers > 0:
            message += f", Выборка: {selection_layers}"
        if errors:
            message += f" | Ошибок: {len(errors)}"

        self.iface.messageBar().pushMessage(
            PLUGIN_NAME,
            f"F_1_2: {message}",
            level=Qgis.Success,
            duration=7
        )

    def _auto_run_selection(self) -> Optional[Dict[str, Any]]:
        """Автоматическая выборка ЗУ/ОКС после загрузки web карт (main thread)

        Вызывает F_2_1_LandSelection для создания выборки по загруженным WFS слоям.
        F_2_1 работает в main thread с QApplication.processEvents() - совместимо с callback.

        Returns:
            Dict со статистикой выборки или None при ошибке
        """
        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_13_selection.Fsm_1_2_13_1_land_selection import F_2_1_LandSelection

            log_info("F_1_2: Запуск автоматической выборки объектов (F_2_1)")

            selection_tool = F_2_1_LandSelection(self.iface)
            selection_tool.set_project_manager(self.project_manager)
            selection_tool.set_layer_manager(self.layer_manager)
            plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            selection_tool.set_plugin_dir(plugin_dir)
            selection_tool.run()

            # Подсчитываем созданные слои выборки
            from Daman_QGIS.constants import (
                LAYER_SELECTION_ZU, LAYER_SELECTION_OKS,
                LAYER_SELECTION_KK, LAYER_SELECTION_NP
            )
            project = QgsProject.instance()
            selection_layer_names = [
                LAYER_SELECTION_ZU, LAYER_SELECTION_OKS,
                LAYER_SELECTION_KK, LAYER_SELECTION_NP
            ]
            count = sum(
                1 for name in selection_layer_names
                if project.mapLayersByName(name)
            )

            log_success(f"F_1_2: Автоматическая выборка завершена, создано {count} слоёв")
            return {'selection_layers': count}

        except Exception as e:
            log_error(f"F_1_2: Ошибка автоматической выборки: {e}")
            self.iface.messageBar().pushMessage(
                PLUGIN_NAME,
                f"Web карты загружены, но выборка не выполнена: {e}",
                level=Qgis.Warning,
                duration=10
            )
            return None

    def _on_load_failed(self, error: str) -> None:
        """Callback при ошибке загрузки (main thread)"""
        log_error(f"F_1_2: Async ошибка - {error}")
        self.iface.messageBar().pushMessage(
            "Ошибка F_1_2",
            f"Ошибка загрузки Web карт: {error}",
            level=Qgis.Critical,
            duration=10
        )

    def _on_load_cancelled(self) -> None:
        """Callback при отмене загрузки (main thread)"""
        log_info("F_1_2: Операция отменена пользователем")
        self.iface.messageBar().pushMessage(
            "F_1_2_Загрузка Web карт",
            "Загрузка отменена",
            level=Qgis.Warning,
            duration=5
        )

    def _add_layers_from_gpkg(self, layer_names: List[str], gpkg_path: str) -> None:
        """Добавление слоёв из GPKG в проект (main thread)"""
        for layer_name in layer_names:
            try:
                uri = f"{gpkg_path}|layername={layer_name}"
                layer = QgsVectorLayer(uri, layer_name, "ogr")
                if layer.isValid():
                    if self.layer_manager:
                        self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
                    else:
                        QgsProject.instance().addMapLayer(layer)
            except Exception as e:
                log_error(f"F_1_2: Ошибка добавления слоя {layer_name}: {str(e)}")

    def _load_main_thread_layers(self, boundary_layer=None) -> Dict[str, int]:
        """Загрузка слоёв, требующих main thread (ЗОУИТ, WMS)

        OSM перенесён в background thread (Fsm_1_2_10._load_osm_data).

        Args:
            boundary_layer: Слой границ работ (если None - получаем из проекта)

        Returns:
            Dict с количеством загруженных слоёв по группам
        """
        stats = {'zouit': 0, 'redline': 0, 'servitude': 0, 'wms': 0}

        # Инициализируем компоненты если нужно
        if not self.api_manager:
            self.api_manager = APIManager()

        # Получаем boundary_layer если не передан
        if boundary_layer is None:
            boundary_layer = QgsProject.instance().mapLayersByName("L_1_1_2_Границы_работ_10_м")
            boundary_layer = boundary_layer[0] if boundary_layer else None

        # ========== ЗОУИТ слои ==========
        if boundary_layer and self.project_manager and self.project_manager.project_db:
            try:
                # Инициализируем необходимые компоненты для ЗОУИТ
                if not self.egrn_loader:
                    from .submodules.Fsm_1_2_1_egrn_loader import Fsm_1_2_1_EgrnLoader
                    self.egrn_loader = Fsm_1_2_1_EgrnLoader(self.iface, self.api_manager)
                if not self.geometry_processor:
                    from .submodules.Fsm_1_2_8_geometry_processor import Fsm_1_2_8_GeometryProcessor
                    self.geometry_processor = Fsm_1_2_8_GeometryProcessor(self.iface)
                if not self.zouit_loader:
                    from .submodules.Fsm_1_2_9_zouit_loader import Fsm_1_2_9_ZouitLoader
                    self.zouit_loader = Fsm_1_2_9_ZouitLoader(
                        self.iface, self.egrn_loader, self.layer_manager,
                        self.geometry_processor, self.api_manager
                    )

                # Type assertions для Pylance (гарантировано после lazy init выше)
                assert self.zouit_loader is not None
                assert self.project_manager is not None
                assert self.project_manager.project_db is not None

                gpkg_path = self.project_manager.project_db.gpkg_path
                zouit_count = self.zouit_loader.load_zouit_layers_final(boundary_layer, gpkg_path, None)
                stats['zouit'] = zouit_count
            except Exception as e:
                log_error(f"F_1_2: Ошибка загрузки ЗОУИТ: {str(e)}")

        # ========== Красные линии (КЛ) ==========
        if boundary_layer and self.project_manager and self.project_manager.project_db:
            try:
                # Lazy init redline_loader
                if not self.redline_loader:
                    from .submodules.Fsm_1_2_11_redline_loader import Fsm_1_2_11_RedlineLoader
                    # Убеждаемся что зависимости инициализированы
                    if not self.egrn_loader:
                        from .submodules.Fsm_1_2_1_egrn_loader import Fsm_1_2_1_EgrnLoader
                        self.egrn_loader = Fsm_1_2_1_EgrnLoader(self.iface, self.api_manager)
                    if not self.geometry_processor:
                        from .submodules.Fsm_1_2_8_geometry_processor import Fsm_1_2_8_GeometryProcessor
                        self.geometry_processor = Fsm_1_2_8_GeometryProcessor(self.iface)
                    self.redline_loader = Fsm_1_2_11_RedlineLoader(
                        self.iface, self.egrn_loader, self.layer_manager,
                        self.geometry_processor
                    )

                gpkg_path = self.project_manager.project_db.gpkg_path
                redline_count = self.redline_loader.load_redline_layers(gpkg_path)
                stats['redline'] = redline_count
            except Exception as e:
                log_error(f"F_1_2: Ошибка загрузки красных линий: {str(e)}")

        # ========== Публичные сервитуты (ПС) ==========
        if boundary_layer and self.project_manager and self.project_manager.project_db:
            try:
                # Lazy init servitude_loader
                if not self.servitude_loader:
                    from .submodules.Fsm_1_2_14_servitude_loader import Fsm_1_2_14_ServitudeLoader
                    # Убеждаемся что зависимости инициализированы
                    if not self.egrn_loader:
                        from .submodules.Fsm_1_2_1_egrn_loader import Fsm_1_2_1_EgrnLoader
                        self.egrn_loader = Fsm_1_2_1_EgrnLoader(self.iface, self.api_manager)
                    if not self.geometry_processor:
                        from .submodules.Fsm_1_2_8_geometry_processor import Fsm_1_2_8_GeometryProcessor
                        self.geometry_processor = Fsm_1_2_8_GeometryProcessor(self.iface)
                    self.servitude_loader = Fsm_1_2_14_ServitudeLoader(
                        self.iface, self.egrn_loader, self.layer_manager,
                        self.geometry_processor
                    )

                gpkg_path = self.project_manager.project_db.gpkg_path
                servitude_count = self.servitude_loader.load_servitude_layers(gpkg_path)
                stats['servitude'] = servitude_count
            except Exception as e:
                log_error(f"F_1_2: Ошибка загрузки публичных сервитутов: {str(e)}")

        # ========== WMS слои (растровые) ==========
        # Инициализируем raster loader
        if not self.raster_loader:
            from .submodules.Fsm_1_2_6_raster_loader import Fsm_1_2_6_RasterLoader
            self.raster_loader = Fsm_1_2_6_RasterLoader(self.iface, self.layer_manager, self.api_manager)

        # Type assertion для Pylance (гарантировано после lazy init выше)
        assert self.raster_loader is not None

        try:
            self.raster_loader.add_nspd_base_layer()
            self.raster_loader.add_cos_layer()
            self.raster_loader.add_google_satellite()
            stats['wms'] = 3
        except Exception as e:
            log_error(f"F_1_2: Ошибка загрузки WMS: {str(e)}")

        return stats

    def _load_egrn_layers(self, boundary_layer: QgsVectorLayer, progress_task) -> Tuple[Any, Optional[str]]:
        """Загрузка векторных слоев ЕГРН через API NSPD

        Args:
            boundary_layer: Слой границ работ
            progress_task: ProgressTask для обновления прогресса

        Returns:
            tuple: (результат, ошибка)
        """
        if not self.egrn_loader:
            return False, "Загрузчик ЕГРН не инициализирован"
        assert self.egrn_loader is not None  # Type narrowing для Pylance
        assert self.atd_loader is not None
        assert self.geometry_processor is not None
        assert self.parent_layer_manager is not None
        assert self.api_manager is not None
        assert self.config_builder is not None

        try:
            project = QgsProject.instance()
            root = project.layerTreeRoot()

            # Проверяем что project_manager инициализирован и проект открыт
            if not self.project_manager or not self.project_manager.project_db:
                return False, "Проект не открыт. Откройте проект через F_0_2_Открыть проект"

            # Получаем путь к GeoPackage из project_db
            gpkg_path = self.project_manager.project_db.gpkg_path

            if not gpkg_path or not os.path.exists(gpkg_path):
                return False, "GeoPackage проекта не найден"

            # НОВАЯ ЛОГИКА: Получаем конфигурацию из Base_layers.json через построитель конфигурации
            # Слои автоматически сортируются по order_layers
            layers_config = self.config_builder.get_layers_config_from_database()

            # Структура для отслеживания загруженных подслоёв (для создания родителей)
            loaded_sublayers = {}  # {(section, group, layer_num, layer): [слои]}

            # ============================================================================
            # ПАРАЛЛЕЛЬНАЯ ЗАГРУЗКА ВСЕХ АТД СЛОЕВ
            # ============================================================================
            from concurrent.futures import ThreadPoolExecutor, as_completed
            import time

            # Извлекаем все АТД слои из конфигурации
            atd_configs = [cfg for cfg in layers_config if cfg['enabled'] and isinstance(cfg.get('category_id'), dict)]

            atd_results = {}  # {layer_name: result_dict}

            if atd_configs:
                start_time = time.time()

                # Получаем max_workers из конфигурации первого АТД endpoint
                # (все АТД endpoints имеют одинаковое значение max_workers)
                first_atd_endpoint = self.api_manager.get_endpoint_by_layer(atd_configs[0]['layer_name'])
                assert first_atd_endpoint is not None, f"Endpoint для {atd_configs[0]['layer_name']} не найден в Base_api_endpoints.json"
                atd_max_workers = first_atd_endpoint['max_workers']

                # Запускаем параллельную загрузку
                with ThreadPoolExecutor(max_workers=atd_max_workers) as executor:
                    # Отправляем все задачи
                    futures = {
                        executor.submit(self.atd_loader.load_single_atd_layer, config, None): config['layer_name']
                        for config in atd_configs
                    }

                    # Собираем результаты по мере завершения
                    completed_count = 0
                    for future in as_completed(futures):
                        # Проверка отмены пользователем
                        if progress_task and progress_task.is_canceled():
                            log_warning(f"F_1_2: Загрузка АТД отменена пользователем")
                            executor.shutdown(wait=False, cancel_futures=True)
                            return False, "Загрузка отменена пользователем"

                        try:
                            # КРИТИЧНО: timeout=180 сек (3 мин) на загрузку ОДНОГО АТД слоя
                            # Если поток зависнет, не блокируем весь executor
                            result = future.result(timeout=180)
                            layer_name = result['config']['layer_name']
                            atd_results[layer_name] = result
                        except TimeoutError:
                            layer_name = futures[future]
                            log_error(f"F_1_2: TIMEOUT (180 сек) загрузки {layer_name} - пропускаем слой")
                            # Не прерываем весь процесс - пропускаем проблемный слой
                        except Exception as e:
                            layer_name = futures[future]
                            log_error(f"F_1_2: Ошибка загрузки {layer_name}: {str(e)}")

                        completed_count += 1

            # Загружаем каждый слой
            for config in layers_config:
                if not config['enabled']:
                    continue

                if progress_task and progress_task.is_canceled():
                    return False, "Загрузка отменена пользователем"

                try:
                    log_info(f"F_1_2: Загрузка векторного слоя: {config['layer_name']}")

                    # Определяем буфер и дробление по типу слоя
                    layer_name = config['layer_name']

                    # АТД слои (административно-территориальное деление)
                    # Используем ПРЕДЗАГРУЖЕННЫЕ данные из параллельной загрузки
                    if isinstance(config['category_id'], dict):
                        log_info(f"F_1_2: Обработка АТД слоя: {layer_name} (из параллельной загрузки)")

                        # Получаем результат из параллельной загрузки
                        if layer_name not in atd_results:
                            log_warning(f"F_1_2: АТД слой {layer_name} не найден в результатах параллельной загрузки")
                            continue

                        result = atd_results[layer_name]
                        layer = result['layer']
                        feature_count = result['feature_count']

                        # Если ничего не загрузилось
                        if not layer or feature_count == 0:
                            log_warning(f"F_1_2: Не удалось загрузить АТД слой {layer_name} ни в одном формате")
                            continue

                    # ОКС - объединённая загрузка 3 типов (Здание + Сооружения + ОНС)
                    elif config['category_id'] == 'oks_combined':
                        # Сохраняем ссылку для использования
                        egrn_loader = self.egrn_loader
                        geometry_provider = egrn_loader.get_boundary_extent  # L_1_1_2 (10м)
                        layer, feature_count = egrn_loader.load_oks_combined(
                            layer_name=config['layer_name'],
                            geometry_provider=geometry_provider,
                            progress_task=None
                        )
                    # ЗОУИТ (Le_1_2_5_21_WFS_ЗОУИТ_ОЗ_ООПТ) - загружается отдельно через load_zouit_layers_final()
                    elif config['category_id'] == 'zouit_layers':
                        log_info(f"F_1_2: Пропуск {config['layer_name']}: загружается через load_zouit_layers_final()")
                        continue
                    # Красные линии - загружаются отдельно через Fsm_1_2_11_RedlineLoader
                    elif config['category_id'] == 'redline_layers':
                        log_info(f"F_1_2: Пропуск {config['layer_name']}: загружается через load_redline_layers()")
                        continue
                    # Публичные сервитуты - загружаются отдельно через Fsm_1_2_14_ServitudeLoader
                    elif config['category_id'] == 'servitude_layers':
                        log_info(f"F_1_2: Пропуск {config['layer_name']}: загружается через load_servitude_layers()")
                        continue
                    # ПРИМЕЧАНИЕ: Старая обработка НП (L_1_2_3_WFS_НП) удалена
                    # Теперь все АТД слои (включая НП как Le_1_2_3_5_АТД_НП_poly) обрабатываются
                    # через специальную логику выше (isinstance(config['category_id'], dict))

                    # ВСЕ ОСТАЛЬНЫЕ - унифицированная загрузка
                    else:
                        # Определяем буфер по Layer_selector из Base_api_endpoints.json
                        boundary_selector = self.api_manager.get_boundary_layer_name(layer_name)
                        if boundary_selector == "L_1_1_3_Границы_работ_500_м":
                            # ЗОУИТ и другие слои с буфером 500м
                            egrn_loader = self.egrn_loader
                            geometry_provider = lambda: egrn_loader.get_boundary_extent(use_500m_buffer=True)
                        else:
                            # Стандартный буфер 10м
                            geometry_provider = self.egrn_loader.get_boundary_extent

                        layer, feature_count = self.egrn_loader.load_layer(
                            layer_name=config['layer_name'],
                            geometry_provider=geometry_provider,
                            progress_task=None
                        )

                    if layer and feature_count > 0:
                        # Определяем чистое имя через централизованную функцию очистки
                        clean_name = self.data_cleanup_manager.sanitize_filename(config['layer_name'])

                        # Переименовываем
                        layer.setName(clean_name)

                        # Сохраняем в GeoPackage
                        saved_layer = self.geometry_processor.save_to_geopackage(layer, gpkg_path, clean_name)
                        if saved_layer:
                            layer = saved_layer

                        # Добавляем слой через layer_manager с явным указанием имени
                        if self.layer_manager:
                            layer.setName(clean_name)
                            self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)

                        # Отслеживаем подслои для создания родительских слоёв
                        if config.get('sublayer_num'):
                            # Это подслой - запоминаем для создания родителя
                            parent_key = (
                                config.get('section_num'),
                                config.get('group_num'),
                                config.get('layer_num'),
                                config.get('layer')
                            )
                            if parent_key not in loaded_sublayers:
                                loaded_sublayers[parent_key] = []
                            loaded_sublayers[parent_key].append(layer)

                        log_success(f"F_1_2: Векторный слой {clean_name} загружен: {feature_count} объектов")

                except Exception as e:
                    log_error(f"F_1_2: Ошибка загрузки слоя {config['layer_name']}: {str(e)}")

            # Создание родительских слоёв из подслоёв
            if loaded_sublayers:
                log_info(f"F_1_2: Создание родительских слоёв из {len(loaded_sublayers)} групп подслоёв")
                self.parent_layer_manager.create_parent_layers(loaded_sublayers, gpkg_path)

            # Безопасный отложенный refresh через QTimer (предотвращает краши)
            from Daman_QGIS.utils import safe_refresh_canvas, REFRESH_HEAVY
            safe_refresh_canvas(REFRESH_HEAVY, delay_ms=200)

            # Подсчитываем результаты
            loaded_count = 0
            empty_count = 0

            for config in layers_config:
                if config['enabled']:
                    found = False
                    for layer in project.mapLayers().values():
                        if layer.name() == config['layer_name']:
                            if layer.featureCount() > 0:
                                loaded_count += 1
                            else:
                                empty_count += 1
                            found = True
                            break
                    if not found:
                        empty_count += 1

            return {'loaded': loaded_count, 'empty': empty_count}, None

        except Exception as e:
            return False, f"Ошибка загрузки векторных слоев ЕГРН: {str(e)}"

    def _load_osm_layers_only(self) -> Tuple[bool, int]:
        """
        Загрузить только OSM слои через Overpass API + OGR (main thread, синхронно).

        NOTE: С FIX-4 основная загрузка OSM выполняется в background thread
        через Fsm_1_2_10._load_osm_data(). Этот метод сохранён для отладки
        и standalone перезагрузки OSM слоёв.

        Returns:
            Tuple[bool, int]: (успех, количество загруженных слоёв)
        """
        try:
            if not self.quickosm_loader:
                log_warning("F_1_2: OSM загрузчик не инициализирован")
                return False, 0
            assert self.quickosm_loader is not None  # Type narrowing для Pylance

            log_info("F_1_2: Запуск загрузки OSM слоёв")

            success, count = self.quickosm_loader.load_all_osm_layers()

            if success:
                log_success(f"F_1_2: OSM слои успешно загружены: {count} слоя(ёв)")

            # Безопасный отложенный refresh через QTimer (предотвращает краши)
            from Daman_QGIS.utils import safe_refresh_canvas, REFRESH_HEAVY
            safe_refresh_canvas(REFRESH_HEAVY, delay_ms=200)

            return True, count

        except Exception as e:
            log_error(f"F_1_2: Ошибка загрузки OSM слоёв: {str(e)}")
            return False, 0

    def _load_fgislk_layers(self) -> Tuple[bool, int]:
        """
        Загрузить ФГИС ЛК слои (секция 4_1_ЛЕС)

        Returns:
            Tuple[bool, int]: (успех, количество загруженных слоёв)
        """
        assert self.geometry_processor is not None  # Type narrowing для Pylance

        try:
            log_info("F_1_2: Запуск загрузки ФГИС ЛК слоёв (секция 4_1_ЛЕС)")

            from .submodules.Fsm_1_2_4_fgislk_loader import Fsm_1_2_4_FgislkLoader

            fgislk_loader = Fsm_1_2_4_FgislkLoader(self.iface, self.api_manager)

            # Создаём временную директорию для тайлов
            import tempfile
            temp_dir = tempfile.mkdtemp(prefix="fgislk_")

            # Получаем путь к GeoPackage проекта
            gpkg_path = self.project_manager.project_db.gpkg_path  # type: ignore[union-attr]
            if not gpkg_path or not os.path.exists(gpkg_path):
                log_error("F_1_2: GeoPackage проекта не найден для ФГИС ЛК слоёв")
                return False, 0

            try:
                # Загружаем слои
                fgislk_layers = fgislk_loader.load_layers(temp_dir)

                if fgislk_layers:
                    log_info(f"F_1_2: Загружено {len(fgislk_layers)} ФГИС ЛК слоёв")

                    # Сохраняем и добавляем каждый слой
                    for layer_name, layer in fgislk_layers.items():
                        try:
                            # Сохраняем в GeoPackage
                            saved_layer = self.geometry_processor.save_to_geopackage(layer, gpkg_path, layer_name)
                            if saved_layer:
                                layer = saved_layer

                            # Добавляем через layer_manager (только для слоёв из Base_layers.json)
                            if self.layer_manager and not "_ФГИС_ЛК_СРАВНИ_С_ЕГРН" in layer_name:
                                layer.setName(layer_name)
                                self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
                            else:
                                # Для временного слоя сравнения - добавляем вручную
                                QgsProject.instance().addMapLayer(layer)

                        except Exception as e:
                            log_error(f"F_1_2: Ошибка обработки ФГИС ЛК слоя {layer_name}: {str(e)}")

                    log_success(f"F_1_2: ФГИС ЛК слои успешно добавлены")

                    # Безопасный отложенный refresh через QTimer (предотвращает краши)
                    from Daman_QGIS.utils import safe_refresh_canvas, REFRESH_HEAVY
                    safe_refresh_canvas(REFRESH_HEAVY, delay_ms=200)

                    return True, len(fgislk_layers)
                else:
                    log_warning("F_1_2: Не удалось загрузить ФГИС ЛК слои")
                    return False, 0

            finally:
                # Удаляем временную директорию
                import shutil
                try:
                    shutil.rmtree(temp_dir)
                except OSError as e:
                    log_warning(f"F_1_2: Не удалось удалить временную директорию {temp_dir}: {e}")

        except Exception as e:
            log_error(f"F_1_2: Ошибка загрузки ФГИС ЛК слоёв: {str(e)}")
            return False, 0