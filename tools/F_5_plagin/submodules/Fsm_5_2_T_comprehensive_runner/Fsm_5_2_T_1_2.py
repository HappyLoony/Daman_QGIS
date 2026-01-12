# -*- coding: utf-8 -*-
"""
Тестовый модуль Fsm_5_2_T_1_2 - Диагностика F_1_2

Проверяет:
- Базовые системы (логирование, GUI, iface)
- Импорт субмодулей F_1_2
- Менеджеры (project_manager, layer_manager)
- Наличие слоя границ работ
- APIManager и endpoints
"""
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import QgsProject
from Daman_QGIS.utils import log_info


class Fsm_5_2_T_1_2:
    """Диагностический тест для F_1_2"""

    def __init__(self, iface, logger):
        """Инициализация теста

        Args:
            iface: Интерфейс QGIS
            logger: Логгер тестирования
        """
        self.iface = iface
        self.logger = logger

    def run_all_tests(self):
        """Запуск всех тестов"""
        self.logger.section("ДИАГНОСТИКА F_1_2: Загрузка Web карт")

        try:
            # СЕКЦИЯ 1: Базовые проверки
            self._test_basic_systems()

            # СЕКЦИЯ 2: Импорт субмодулей
            self._test_submodule_imports()

            # СЕКЦИЯ 3: Менеджеры проекта
            self._test_managers()

            # СЕКЦИЯ 4: Слой границ работ
            self._test_boundary_layer()

            # СЕКЦИЯ 5: APIManager
            self._test_api_manager()

            # СЕКЦИЯ 6: Инициализация всех субмодулей F_1_2
            self._test_submodule_initialization()

            # СЕКЦИЯ 7: Тестовый вызов методов загрузки (поиск зависания)
            self._test_loading_methods()

            self.logger.success("===== ВСЕ ДИАГНОСТИЧЕСКИЕ ПРОВЕРКИ ПРОЙДЕНЫ ======")

        except Exception as e:
            self.logger.error(f"Критическая ошибка в тесте: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        # Итоговая сводка
        self.logger.summary()

    def _test_basic_systems(self):
        """СЕКЦИЯ 1: Базовые системы"""
        self.logger.section("1. Базовые системы")

        # Тест 1.1: Логирование
        self.logger.info("Проверка системы логирования...")
        log_info("Fsm_5_2_T_1_2: Тестовое сообщение в лог-файл")
        self.logger.success("Система логирования работает")

        # Тест 1.2: iface
        self.logger.info("Проверка iface...")
        if self.iface:
            self.logger.success(f"iface доступен: {type(self.iface).__name__}")
        else:
            self.logger.fail("iface недоступен!")

        # Тест 1.3: QgsProject
        self.logger.info("Проверка QgsProject...")
        project = QgsProject.instance()
        if project:
            project_path = project.absolutePath()
            if project_path:
                self.logger.success(f"Проект открыт: {project_path}")
            else:
                self.logger.warning("Проект QGIS не открыт (можно продолжать)")
        else:
            self.logger.fail("QgsProject.instance() вернул None!")

    def _test_submodule_imports(self):
        """СЕКЦИЯ 2: Импорт субмодулей F_1_2"""
        self.logger.section("2. Импорт субмодулей F_1_2")

        # Тест 2.1: APIManager
        self.logger.info("Импорт APIManager...")
        try:
            from Daman_QGIS.managers import APIManager
            self.logger.success("APIManager импортирован")
        except Exception as e:
            self.logger.fail(f"Ошибка импорта APIManager: {str(e)}")

        # Тест 2.2: EgrnLoader
        self.logger.info("Импорт Fsm_1_2_1_EgrnLoader...")
        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_1_egrn_loader import Fsm_1_2_1_EgrnLoader
            self.logger.success("Fsm_1_2_1_EgrnLoader импортирован")
        except Exception as e:
            self.logger.fail(f"Ошибка импорта EgrnLoader: {str(e)}")

        # Тест 2.3: QuickOSMLoader
        self.logger.info("Импорт Fsm_1_2_3_QuickOSMLoader...")
        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_3_quickosm_loader import Fsm_1_2_3_QuickOSMLoader
            self.logger.success("Fsm_1_2_3_QuickOSMLoader импортирован")
        except Exception as e:
            self.logger.fail(f"Ошибка импорта QuickOSMLoader: {str(e)}")

        # Тест 2.4: GeometryProcessor
        self.logger.info("Импорт Fsm_1_2_8_GeometryProcessor...")
        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_8_geometry_processor import Fsm_1_2_8_GeometryProcessor
            self.logger.success("Fsm_1_2_8_GeometryProcessor импортирован")
        except Exception as e:
            self.logger.fail(f"Ошибка импорта GeometryProcessor: {str(e)}")

    def _test_managers(self):
        """СЕКЦИЯ 3: Менеджеры проекта"""
        self.logger.section("3. Менеджеры проекта")

        # Тест 3.1: ProjectManager
        self.logger.info("Проверка ProjectManager...")
        try:
            from Daman_QGIS.managers import ProjectManager

            # Получаем реальный путь проекта
            project = QgsProject.instance()
            project_path = project.absolutePath()

            if not project_path:
                self.logger.warning("Проект QGIS не сохранен на диске")
                return

            self.logger.data("Путь проекта", project_path)

            # Проверяем наличие GPKG файла вручную
            import os
            # ПРИМЕЧАНИЕ: Нормализуем путь для Windows (устраняем смешанные слэши)
            gpkg_file_path = os.path.normpath(os.path.join(project_path, "project.gpkg"))
            if os.path.exists(gpkg_file_path):
                self.logger.success(f"GPKG файл существует: {gpkg_file_path}")
                file_size = os.path.getsize(gpkg_file_path)
                self.logger.data("Размер файла", f"{file_size} байт")
            else:
                # В тестовой среде без реального проекта это ожидаемо
                self.logger.warning(f"GPKG файл не найден: {gpkg_file_path} (тестовая среда)")
                return

            # ПРАВИЛЬНОЕ использование: plugin_dir из константы, затем init_from_native_project()
            plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            self.logger.data("Plugin dir", plugin_dir)

            pm = ProjectManager(self.iface, plugin_dir)
            self.logger.success(f"ProjectManager создан: {type(pm).__name__}")

            # Инициализируем из открытого QGIS проекта
            self.logger.info("Вызов init_from_native_project()...")
            success = pm.init_from_native_project()

            if success:
                self.logger.success("init_from_native_project() успешно")
                if pm.project_db:
                    self.logger.success("project_db доступен")
                    gpkg_path = pm.project_db.gpkg_path
                    self.logger.data("GPKG путь", str(gpkg_path))
                    self.logger.data("current_project", str(pm.current_project))
                else:
                    self.logger.fail("project_db = None после init_from_native_project()")
            else:
                self.logger.fail("init_from_native_project() вернул False")

        except Exception as e:
            self.logger.error(f"Ошибка создания ProjectManager: {str(e)}")

        # Тест 3.2: LayerManager
        self.logger.info("Проверка LayerManager...")
        try:
            from Daman_QGIS.managers import LayerManager
            lm = LayerManager(self.iface)
            if lm:
                self.logger.success(f"LayerManager создан: {type(lm).__name__}")
            else:
                self.logger.fail("LayerManager = None")
        except Exception as e:
            self.logger.error(f"Ошибка создания LayerManager: {str(e)}")

    def _test_boundary_layer(self):
        """СЕКЦИЯ 4: Слой границ работ"""
        self.logger.section("4. Слой границ работ L_1_1_2")

        project = QgsProject.instance()
        boundary_layer = None

        self.logger.info("Поиск слоя L_1_1_2_Границы_работ_10_м...")

        for layer in project.mapLayers().values():
            if layer.name() == "L_1_1_2_Границы_работ_10_м":
                boundary_layer = layer
                break

        if boundary_layer:
            self.logger.success(f"Слой найден: {boundary_layer.name()}")

            if boundary_layer.isValid():
                self.logger.success("Слой валиден")
            else:
                self.logger.fail("Слой невалиден!")

            feature_count = boundary_layer.featureCount()
            self.logger.data("Количество объектов", str(feature_count))

            if feature_count > 0:
                self.logger.success(f"Слой содержит {feature_count} объектов")
            else:
                self.logger.warning("Слой пустой!")

            # Проверяем CRS
            crs = boundary_layer.crs()
            self.logger.data("CRS", f"{crs.authid()} - {crs.description()}")
        else:
            self.logger.warning("Слой L_1_1_2_Границы_работ_10_м НЕ НАЙДЕН")
            self.logger.warning("Для полного теста F_1_2 создайте слой через F_1_1")

    def _test_api_manager(self):
        """СЕКЦИЯ 5: APIManager и endpoints"""
        self.logger.section("5. APIManager и endpoints")

        try:
            from Daman_QGIS.managers import APIManager

            self.logger.info("Создание экземпляра APIManager...")
            api_manager = APIManager()
            self.logger.success("APIManager создан")

            # Проверяем endpoints
            all_endpoints = api_manager.get_all_endpoints()
            self.logger.data("Всего endpoints", str(len(all_endpoints)))

            if len(all_endpoints) > 0:
                self.logger.success(f"Загружено {len(all_endpoints)} endpoints")

                # Анализируем структуру первого endpoint'а
                if all_endpoints:
                    first = all_endpoints[0]
                    self.logger.data("Структура endpoint", f"Ключи: {list(first.keys())}")

                    # Определяем правильное поле для категоризации
                    category_field = None
                    if 'api_group' in first:
                        category_field = 'api_group'
                    elif 'source' in first:
                        category_field = 'source'
                    elif 'category' in first:
                        category_field = 'category'
                    elif 'type' in first:
                        category_field = 'type'

                    if category_field:
                        self.logger.data("Поле категории", category_field)

                        # Проверяем категории
                        egrn_count = len([e for e in all_endpoints if e.get(category_field) == 'egrn'])
                        fgislk_count = len([e for e in all_endpoints if e.get(category_field) == 'fgislk'])
                        osm_count = len([e for e in all_endpoints if e.get(category_field) == 'osm'])
                        zouit_count = len([e for e in all_endpoints if e.get(category_field) == 'zouit'])
                        wms_count = len([e for e in all_endpoints if e.get(category_field) == 'wms'])

                        self.logger.data("ЕГРН endpoints", str(egrn_count))
                        self.logger.data("ФГИС ЛК endpoints", str(fgislk_count))
                        self.logger.data("OSM endpoints", str(osm_count))
                        self.logger.data("ЗОУИТ endpoints", str(zouit_count))
                        self.logger.data("WMS endpoints", str(wms_count))

                        # Показываем уникальные значения категорий
                        unique_categories = set(e.get(category_field, 'N/A') for e in all_endpoints)
                        self.logger.data("Уникальные категории", str(sorted(unique_categories)))

                        # Показываем также api_type если есть
                        if 'api_type' in first:
                            unique_types = set(e.get('api_type', 'N/A') for e in all_endpoints)
                            self.logger.data("Уникальные api_type", str(sorted(unique_types)))
                    else:
                        self.logger.warning("Не найдено поле категоризации (api_group/source/category/type)")

                    # Показываем несколько примеров endpoint'ов
                    self.logger.info("Примеры endpoints:")
                    for i, ep in enumerate(all_endpoints[:3]):  # Первые 3 примера
                        layer_name = ep.get('layer_name', 'N/A')
                        api_group = ep.get('api_group', 'N/A')
                        api_type = ep.get('api_type', 'N/A')
                        self.logger.data(f"  [{i+1}] {layer_name}", f"group={api_group}, type={api_type}")
            else:
                self.logger.fail("Нет доступных endpoints!")

        except Exception as e:
            self.logger.error(f"Ошибка работы с APIManager: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def _test_submodule_initialization(self):
        """СЕКЦИЯ 6: Инициализация всех субмодулей F_1_2 (как в реальном запуске)"""
        self.logger.section("6. Инициализация всех субмодулей F_1_2")

        try:
            # Подготовка: получаем boundary_layer и api_manager
            from Daman_QGIS.managers import APIManager, ProjectManager, LayerManager

            project = QgsProject.instance()
            boundary_layer = None
            for layer in project.mapLayers().values():
                if layer.name() == "L_1_1_2_Границы_работ_10_м":
                    boundary_layer = layer
                    break

            if not boundary_layer:
                # В тестовой среде без проекта это ожидаемо
                self.logger.warning("Слой L_1_1_2_Границы_работ_10_м не найден (тестовая среда)")
                self.logger.info("Пропускаем тесты субмодулей, требующих слой границ")
                return

            # Инициализируем менеджеры
            import os
            plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            project_manager = ProjectManager(self.iface, plugin_dir)
            project_manager.init_from_native_project()
            layer_manager = LayerManager(self.iface)
            api_manager = APIManager()

            self.logger.success(f"Подготовка завершена: boundary_layer={boundary_layer.name()}")

            # Тест 6.1: EgrnLoader
            self.logger.info("6.1. Инициализация Fsm_1_2_1_EgrnLoader...")
            try:
                from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_1_egrn_loader import Fsm_1_2_1_EgrnLoader
                egrn_loader = Fsm_1_2_1_EgrnLoader(self.iface, api_manager)
                self.logger.success(f"EgrnLoader создан: {type(egrn_loader).__name__}")

                # Проверяем наличие методов
                has_load = hasattr(egrn_loader, 'load_egrn_layers')
                has_cache = hasattr(egrn_loader, 'clear_cache')
                self.logger.data("  Методы", f"load_egrn_layers={has_load}, clear_cache={has_cache}")
            except Exception as e:
                self.logger.fail(f"Ошибка EgrnLoader: {str(e)}")

            # Тест 6.2: QuickOSMLoader
            self.logger.info("6.2. Инициализация Fsm_1_2_3_QuickOSMLoader...")
            try:
                from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_3_quickosm_loader import Fsm_1_2_3_QuickOSMLoader
                quickosm_loader = Fsm_1_2_3_QuickOSMLoader(self.iface, layer_manager, project_manager, api_manager)
                self.logger.success(f"QuickOSMLoader создан: {type(quickosm_loader).__name__}")

                # Проверяем наличие методов
                has_load = hasattr(quickosm_loader, 'load_osm_layers')
                self.logger.data("  Методы", f"load_osm_layers={has_load}")
            except Exception as e:
                self.logger.fail(f"Ошибка QuickOSMLoader: {str(e)}")

            # Тест 6.3: GeometryProcessor
            self.logger.info("6.3. Инициализация Fsm_1_2_8_GeometryProcessor...")
            try:
                from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_8_geometry_processor import Fsm_1_2_8_GeometryProcessor
                geometry_processor = Fsm_1_2_8_GeometryProcessor(self.iface)
                self.logger.success(f"GeometryProcessor создан: {type(geometry_processor).__name__}")

                # Проверяем наличие методов
                has_process = hasattr(geometry_processor, 'process_geometry')
                has_buffer = hasattr(geometry_processor, 'create_buffer')
                self.logger.data("  Методы", f"process_geometry={has_process}, create_buffer={has_buffer}")
            except Exception as e:
                self.logger.fail(f"Ошибка GeometryProcessor: {str(e)}")

            # Тест 6.4: AtdLoader
            self.logger.info("6.4. Инициализация Fsm_1_2_5_AtdLoader...")
            try:
                from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_5_atd_loader import Fsm_1_2_5_AtdLoader
                atd_loader = Fsm_1_2_5_AtdLoader(self.iface, egrn_loader, api_manager)
                self.logger.success(f"AtdLoader создан: {type(atd_loader).__name__}")
            except Exception as e:
                self.logger.fail(f"Ошибка AtdLoader: {str(e)}")

            # Тест 6.5: RasterLoader
            self.logger.info("6.5. Инициализация Fsm_1_2_6_RasterLoader...")
            try:
                from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_6_raster_loader import Fsm_1_2_6_RasterLoader
                raster_loader = Fsm_1_2_6_RasterLoader(self.iface, layer_manager, api_manager)
                self.logger.success(f"RasterLoader created: {type(raster_loader).__name__}")

                # Проверяем методы
                has_google = hasattr(raster_loader, 'add_google_satellite')
                has_nspd = hasattr(raster_loader, 'add_nspd_base_layer')
                has_cos = hasattr(raster_loader, 'add_cos_layer')
                self.logger.data("  Методы", f"google={has_google}, nspd={has_nspd}, cos={has_cos}")
            except Exception as e:
                self.logger.fail(f"Ошибка RasterLoader: {str(e)}")

            # Тест 6.6: ParentLayerManager
            self.logger.info("6.6. Инициализация Fsm_1_2_7_ParentLayerManager...")
            try:
                from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_7_parent_layer_manager import Fsm_1_2_7_ParentLayerManager
                parent_layer_manager = Fsm_1_2_7_ParentLayerManager(self.iface, layer_manager)
                self.logger.success(f"ParentLayerManager создан: {type(parent_layer_manager).__name__}")
            except Exception as e:
                self.logger.fail(f"Ошибка ParentLayerManager: {str(e)}")

            # Тест 6.7: ZouitLoader
            self.logger.info("6.7. Инициализация Fsm_1_2_9_ZouitLoader...")
            try:
                from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_9_zouit_loader import Fsm_1_2_9_ZouitLoader
                zouit_loader = Fsm_1_2_9_ZouitLoader(self.iface, egrn_loader, layer_manager, geometry_processor, api_manager)
                self.logger.success(f"ZouitLoader создан: {type(zouit_loader).__name__}")

                # Проверяем метод
                has_load = hasattr(zouit_loader, 'load_zouit_layers_final')
                self.logger.data("  Методы", f"load_zouit_layers_final={has_load}")
            except Exception as e:
                self.logger.fail(f"Ошибка ZouitLoader: {str(e)}")

            self.logger.success("✓ Все субмодули F_1_2 успешно инициализированы")

        except Exception as e:
            self.logger.error(f"Критическая ошибка инициализации субмодулей: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def _test_loading_methods(self):
        """СЕКЦИЯ 7: Тестовый вызов методов загрузки (поиск зависания)"""
        self.logger.section("7. Тестовый вызов методов загрузки")

        self.logger.warning("⚠ ВНИМАНИЕ: Эта секция может вызвать зависание!")
        self.logger.warning("⚠ Если тест застрянет, последний лог покажет проблемный метод")

        try:
            # Подготовка
            from Daman_QGIS.managers import APIManager, ProjectManager, LayerManager
            from Daman_QGIS.tools.F_1_data.F_1_2_load_wms import F_1_2_LoadWMS

            import os
            project = QgsProject.instance()
            boundary_layer = None
            for layer in project.mapLayers().values():
                if layer.name() == "L_1_1_2_Границы_работ_10_м":
                    boundary_layer = layer
                    break

            if not boundary_layer:
                # В тестовой среде без проекта это ожидаемо
                self.logger.warning("Слой L_1_1_2_Границы_работ_10_м не найден (тестовая среда)")
                self.logger.info("Пропускаем тесты методов загрузки")
                return

            # Создаём F_1_2 инстанс
            plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            project_manager = ProjectManager(self.iface, plugin_dir)
            project_manager.init_from_native_project()
            layer_manager = LayerManager(self.iface)

            f_1_2 = F_1_2_LoadWMS(self.iface)
            f_1_2.set_project_manager(project_manager)
            f_1_2.set_layer_manager(layer_manager)

            self.logger.success(f"F_1_2 инстанс создан")

            # Тест 7.1: auto_cleanup_layers()
            self.logger.info("7.1. Вызов auto_cleanup_layers()...")
            try:
                f_1_2.auto_cleanup_layers()
                self.logger.success("auto_cleanup_layers() завершён")
            except Exception as e:
                self.logger.fail(f"Ошибка auto_cleanup_layers(): {str(e)}")

            # Тест 7.2: Проверка APIManager инициализации
            self.logger.info("7.2. Инициализация APIManager...")
            try:
                api_manager = APIManager()
                f_1_2.api_manager = api_manager
                self.logger.success(f"APIManager инициализирован: {len(api_manager.get_all_endpoints())} endpoints")
            except Exception as e:
                self.logger.fail(f"Ошибка APIManager: {str(e)}")
                return

            # Тест 7.3: Инициализация субмодулей F_1_2 (ПОСТЕПЕННО, по одному)
            self.logger.info("7.3. Инициализация субмодулей F_1_2 (постепенно)...")

            # ========== Тест 7.3.1: EgrnLoader ==========
            self.logger.info("7.3.1. EgrnLoader...")
            self.logger.warning(">>> НАЧАЛО 7.3.1: ИМПОРТ Fsm_1_2_1_EgrnLoader")
            try:
                from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_1_egrn_loader import Fsm_1_2_1_EgrnLoader
                self.logger.info("  ✓ Импорт OK")
                self.logger.warning(">>> СОЗДАНИЕ экземпляра EgrnLoader")
                f_1_2.egrn_loader = Fsm_1_2_1_EgrnLoader(self.iface, api_manager)
                self.logger.success("  ✓ 7.3.1 ЗАВЕРШЁН: EgrnLoader инициализирован")
            except Exception as e:
                self.logger.fail(f"✗ ОШИБКА 7.3.1: {str(e)}")
                return

            # ========== Тест 7.3.2: QuickOSMLoader ==========
            self.logger.info("7.3.2. QuickOSMLoader...")
            self.logger.warning(">>> НАЧАЛО 7.3.2: ИМПОРТ Fsm_1_2_3_QuickOSMLoader")
            try:
                from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_3_quickosm_loader import Fsm_1_2_3_QuickOSMLoader
                self.logger.info("  ✓ Импорт OK")
                self.logger.warning(">>> СОЗДАНИЕ экземпляра QuickOSMLoader")
                f_1_2.quickosm_loader = Fsm_1_2_3_QuickOSMLoader(self.iface, layer_manager, project_manager, api_manager)
                self.logger.success("  ✓ 7.3.2 ЗАВЕРШЁН: QuickOSMLoader инициализирован")
            except Exception as e:
                self.logger.fail(f"✗ ОШИБКА 7.3.2: {str(e)}")
                return

            # ========== Тест 7.3.3: GeometryProcessor ==========
            self.logger.info("7.3.3. GeometryProcessor...")
            self.logger.warning(">>> НАЧАЛО 7.3.3: ИМПОРТ Fsm_1_2_8_GeometryProcessor")
            try:
                from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_8_geometry_processor import Fsm_1_2_8_GeometryProcessor
                self.logger.info("  ✓ Импорт OK")
                self.logger.warning(">>> СОЗДАНИЕ экземпляра GeometryProcessor")
                f_1_2.geometry_processor = Fsm_1_2_8_GeometryProcessor(self.iface)
                self.logger.success("  ✓ 7.3.3 ЗАВЕРШЁН: GeometryProcessor инициализирован")
            except Exception as e:
                self.logger.fail(f"✗ ОШИБКА 7.3.3: {str(e)}")
                return

            # ========== Тест 7.3.4: AtdLoader ==========
            self.logger.info("7.3.4. AtdLoader (КРИТИЧЕН для _load_egrn_layers)...")
            self.logger.warning(">>> НАЧАЛО 7.3.4: ИМПОРТ Fsm_1_2_5_AtdLoader")
            try:
                from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_5_atd_loader import Fsm_1_2_5_AtdLoader
                self.logger.info("  ✓ Импорт OK")
                self.logger.warning(">>> СОЗДАНИЕ экземпляра AtdLoader")
                f_1_2.atd_loader = Fsm_1_2_5_AtdLoader(self.iface, f_1_2.egrn_loader, api_manager)
                self.logger.success("  ✓ 7.3.4 ЗАВЕРШЁН: AtdLoader инициализирован")
            except Exception as e:
                self.logger.fail(f"✗ ОШИБКА 7.3.4: {str(e)}")
                return

            # ========== Тест 7.3.5: RasterLoader ==========
            self.logger.info("7.3.5. RasterLoader...")
            self.logger.warning(">>> НАЧАЛО 7.3.5: ИМПОРТ Fsm_1_2_6_RasterLoader")
            try:
                from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_6_raster_loader import Fsm_1_2_6_RasterLoader
                self.logger.info("  ✓ Импорт OK")
                self.logger.warning(">>> СОЗДАНИЕ экземпляра RasterLoader")
                f_1_2.raster_loader = Fsm_1_2_6_RasterLoader(self.iface, layer_manager, api_manager)
                self.logger.success("  ✓ 7.3.5 ЗАВЕРШЁН: RasterLoader инициализирован")
            except Exception as e:
                self.logger.fail(f"✗ ОШИБКА 7.3.5: {str(e)}")
                return

            # ========== Тест 7.3.6: ParentLayerManager ==========
            self.logger.info("7.3.6. ParentLayerManager...")
            self.logger.warning(">>> НАЧАЛО 7.3.6: ИМПОРТ Fsm_1_2_7_ParentLayerManager")
            try:
                from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_7_parent_layer_manager import Fsm_1_2_7_ParentLayerManager
                self.logger.info("  ✓ Импорт OK")
                self.logger.warning(">>> СОЗДАНИЕ экземпляра ParentLayerManager")
                f_1_2.parent_layer_manager = Fsm_1_2_7_ParentLayerManager(self.iface, layer_manager)
                self.logger.success("  ✓ 7.3.6 ЗАВЕРШЁН: ParentLayerManager инициализирован")
            except Exception as e:
                self.logger.fail(f"✗ ОШИБКА 7.3.6: {str(e)}")
                return

            # ========== Тест 7.3.7: ZouitLoader ==========
            self.logger.info("7.3.7. ZouitLoader...")
            self.logger.warning(">>> НАЧАЛО 7.3.7: ИМПОРТ Fsm_1_2_9_ZouitLoader")
            try:
                from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_9_zouit_loader import Fsm_1_2_9_ZouitLoader
                self.logger.info("  ✓ Импорт OK")
                self.logger.warning(">>> СОЗДАНИЕ экземпляра ZouitLoader")
                f_1_2.zouit_loader = Fsm_1_2_9_ZouitLoader(self.iface, f_1_2.egrn_loader, layer_manager, f_1_2.geometry_processor, api_manager)
                self.logger.success("  ✓ 7.3.7 ЗАВЕРШЁН: ZouitLoader инициализирован")
            except Exception as e:
                self.logger.fail(f"✗ ОШИБКА 7.3.7: {str(e)}")
                return

            self.logger.success("✓✓✓ ВСЕ 7 СУБМОДУЛЕЙ ИНИЦИАЛИЗИРОВАНЫ УСПЕШНО ✓✓✓")

            # Тест 7.4: Вызов _load_egrn_layers()
            self.logger.info("7.4. Вызов _load_egrn_layers()...")
            self.logger.warning(">>> ВХОД В _load_egrn_layers() - если тест зависнет ЗДЕСЬ, проблема в ЕГРН загрузке")
            try:
                result, error = f_1_2._load_egrn_layers(boundary_layer, None)
                if error:
                    self.logger.fail(f"_load_egrn_layers() вернул ошибку: {error}")
                    self.logger.data("  result", str(result))
                else:
                    self.logger.success(f"_load_egrn_layers() завершён успешно")
                    self.logger.data("  result", str(result))
            except Exception as e:
                self.logger.fail(f"ИСКЛЮЧЕНИЕ в _load_egrn_layers(): {str(e)}")
                import traceback
                self.logger.data("  Traceback", traceback.format_exc())
            self.logger.warning("<<< ВЫХОД ИЗ _load_egrn_layers()")

            # Тест 7.5: Инициализация QuickOSMLoader
            self.logger.info("7.5. Инициализация QuickOSMLoader...")
            try:
                from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_3_quickosm_loader import Fsm_1_2_3_QuickOSMLoader
                f_1_2.quickosm_loader = Fsm_1_2_3_QuickOSMLoader(self.iface, layer_manager, project_manager, api_manager)
                self.logger.success("QuickOSMLoader инициализирован")
            except Exception as e:
                self.logger.fail(f"Ошибка QuickOSMLoader: {str(e)}")

            # Тест 7.6: Вызов _load_osm_layers_only()
            self.logger.info("7.6. Вызов _load_osm_layers_only()...")
            self.logger.warning(">>> ВХОД В _load_osm_layers_only() - если тест зависнет ЗДЕСЬ, проблема в OSM загрузке")
            try:
                osm_success, osm_count = f_1_2._load_osm_layers_only()
                self.logger.success(f"_load_osm_layers_only() завершён: success={osm_success}, count={osm_count}")
            except Exception as e:
                self.logger.fail(f"Ошибка _load_osm_layers_only(): {str(e)}")
            self.logger.warning("<<< ВЫХОД ИЗ _load_osm_layers_only()")

            # Тест 7.7: Инициализация RasterLoader
            self.logger.info("7.7. Инициализация RasterLoader...")
            try:
                from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_6_raster_loader import Fsm_1_2_6_RasterLoader
                f_1_2.raster_loader = Fsm_1_2_6_RasterLoader(self.iface, layer_manager, api_manager)
                self.logger.success("RasterLoader инициализирован")
            except Exception as e:
                self.logger.fail(f"Ошибка RasterLoader: {str(e)}")

            # Тест 7.8: Вызов add_google_satellite()
            self.logger.info("7.8. Вызов add_google_satellite()...")
            self.logger.warning(">>> ВХОД В add_google_satellite()")
            try:
                f_1_2.raster_loader.add_google_satellite()
                self.logger.success("add_google_satellite() завершён")
            except Exception as e:
                self.logger.fail(f"Ошибка add_google_satellite(): {str(e)}")
            self.logger.warning("<<< ВЫХОД ИЗ add_google_satellite()")

            self.logger.success("✓ Все тестовые вызовы методов завершены БЕЗ зависания")

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестирования методов: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
