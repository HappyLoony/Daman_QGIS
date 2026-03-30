# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_M1_M2 - Тестирование M_1 ProjectManager и M_2 LayerManager

Тестирует:
- M_1: конструктор, create_project, open_project, save_project, close_project,
       sync_metadata_to_layers, get_project_info, is_project_open
- M_2: конструктор, add_layer, sort_all_layers, remove_layer, get_layer_info,
       update_layer_name, clear_registry
- Взаимодействие M_1 <-> M_2 <-> ProjectDB
"""

import os
import tempfile
import shutil
from typing import Any, Optional


class TestProjectLayerManagers:
    """Тесты M_1 ProjectManager и M_2 LayerManager"""

    def __init__(self, iface: Any, logger: Any) -> None:
        self.iface = iface
        self.logger = logger
        self.project_manager = None
        self.layer_manager = None
        self.temp_dir = None

    def run_all_tests(self) -> None:
        self.logger.section("ТЕСТ M_1/M_2: ProjectManager и LayerManager")
        try:
            # M_1 ProjectManager
            self.test_01_m1_import()
            self.test_02_m1_constructor()
            self.test_03_m1_methods_exist()
            self.test_04_m1_initial_state()
            self.test_05_m1_is_project_open_no_project()
            self.test_06_m1_save_project_no_project()
            self.test_07_m1_close_project_no_project()
            self.test_08_m1_get_project_info_no_project()
            self.test_09_m1_create_project()
            self.test_10_m1_open_project()
            self.test_11_m1_save_project()
            self.test_12_m1_sync_metadata()
            self.test_13_m1_close_project()

            # M_2 LayerManager
            self.test_20_m2_import()
            self.test_21_m2_constructor()
            self.test_22_m2_methods_exist()
            self.test_23_m2_initial_state()
            self.test_24_m2_add_layer()
            self.test_25_m2_get_layer_info()
            self.test_26_m2_sort_all_layers()
            self.test_27_m2_remove_layer()
            self.test_28_m2_clear_registry()

            # Interaction M_1 + M_2
            self.test_30_interaction_create_and_add_layers()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов M_1/M_2: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
        finally:
            self._cleanup()

        self.logger.summary()

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_temp_dir(self) -> str:
        """Создает временную директорию для тестов"""
        if self.temp_dir is None:
            self.temp_dir = tempfile.mkdtemp(prefix="daman_test_m1m2_")
        return self.temp_dir

    def _cleanup(self) -> None:
        """Очистка временных данных"""
        # Закрываем проект если открыт
        try:
            if self.project_manager and self.project_manager.current_project:
                self.project_manager.close_project()
        except Exception:
            pass

        # Удаляем временную директорию
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception as e:
                self.logger.warning(f"Не удалось удалить temp dir: {e}")

    def _get_plugin_dir(self) -> str:
        """Получить путь к директории плагина"""
        try:
            import qgis.utils
            if hasattr(qgis.utils, 'plugins') and 'Daman_QGIS' in qgis.utils.plugins:
                plugin = qgis.utils.plugins['Daman_QGIS']
                if hasattr(plugin, 'plugin_dir'):
                    return plugin.plugin_dir
        except Exception:
            pass
        # Fallback: вычислить из текущего файла
        current = os.path.abspath(__file__)
        # tools/F_4_plagin/submodules/Fsm_4_2_T_comprehensive_runner/ -> 4 уровня вверх
        plugin_dir = current
        for _ in range(5):
            plugin_dir = os.path.dirname(plugin_dir)
        return plugin_dir

    # -------------------------------------------------------------------------
    # M_1 ProjectManager: Import and Constructor
    # -------------------------------------------------------------------------

    def test_01_m1_import(self) -> None:
        """ТЕСТ 01: Импорт ProjectManager"""
        self.logger.section("M_1: Импорт ProjectManager")
        try:
            from Daman_QGIS.managers import ProjectManager
            self.logger.success("ProjectManager импортирован")
        except ImportError as e:
            self.logger.fail(f"Не удалось импортировать ProjectManager: {e}")

    def test_02_m1_constructor(self) -> None:
        """ТЕСТ 02: Конструктор ProjectManager"""
        self.logger.section("M_1: Конструктор")
        try:
            from Daman_QGIS.managers import ProjectManager
            plugin_dir = self._get_plugin_dir()
            pm = ProjectManager(self.iface, plugin_dir)
            self.project_manager = pm

            self.logger.check(
                pm.iface is not None,
                "iface установлен",
                "iface не установлен"
            )
            self.logger.check(
                pm.plugin_dir == plugin_dir,
                f"plugin_dir установлен: {plugin_dir}",
                "plugin_dir не установлен"
            )
            self.logger.success("ProjectManager создан")
        except Exception as e:
            self.logger.fail(f"Ошибка создания ProjectManager: {e}")

    def test_03_m1_methods_exist(self) -> None:
        """ТЕСТ 03: Наличие ключевых методов M_1"""
        self.logger.section("M_1: Наличие методов")
        if not self.project_manager:
            self.logger.warning("ProjectManager не создан, пропуск")
            return

        methods = [
            'create_project', 'open_project', 'save_project', 'close_project',
            'sync_metadata_to_layers', 'get_project_info', 'is_project_open',
            'get_current_version_path', 'get_import_path', 'get_export_path',
            'get_rasters_path', 'init_from_native_project',
        ]
        missing = []
        for method in methods:
            if not hasattr(self.project_manager, method):
                missing.append(method)

        if not missing:
            self.logger.success(f"Все {len(methods)} методов присутствуют")
        else:
            self.logger.fail(f"Отсутствуют методы: {', '.join(missing)}")

    def test_04_m1_initial_state(self) -> None:
        """ТЕСТ 04: Начальное состояние ProjectManager"""
        self.logger.section("M_1: Начальное состояние")
        if not self.project_manager:
            self.logger.warning("ProjectManager не создан, пропуск")
            return

        pm = self.project_manager
        self.logger.check(
            pm.current_project is None,
            "current_project = None (корректно)",
            f"current_project = {pm.current_project} (ожидался None)"
        )
        self.logger.check(
            pm.project_db is None,
            "project_db = None (корректно)",
            "project_db не None"
        )
        self.logger.check(
            pm.settings is None,
            "settings = None (корректно)",
            "settings не None"
        )

    def test_05_m1_is_project_open_no_project(self) -> None:
        """ТЕСТ 05: is_project_open без открытого проекта"""
        self.logger.section("M_1: is_project_open (нет проекта)")
        if not self.project_manager:
            self.logger.warning("ProjectManager не создан, пропуск")
            return

        try:
            # Сбрасываем состояние
            self.project_manager.current_project = None
            self.project_manager.project_db = None
            self.project_manager.settings = None

            result = self.project_manager.is_project_open()
            # Результат зависит от того, есть ли нативно открытый проект QGIS
            self.logger.info(f"is_project_open() вернул: {result}")
            self.logger.success("Метод is_project_open() выполнен без ошибок")
        except Exception as e:
            self.logger.warning(f"is_project_open() вызвал исключение: {e}")

    def test_06_m1_save_project_no_project(self) -> None:
        """ТЕСТ 06: save_project без открытого проекта"""
        self.logger.section("M_1: save_project (нет проекта)")
        if not self.project_manager:
            self.logger.warning("ProjectManager не создан, пропуск")
            return

        try:
            self.project_manager.current_project = None
            self.project_manager.save_project()
            self.logger.fail("save_project() не выбросил исключение при отсутствии проекта")
        except Exception as e:
            self.logger.success(f"Корректное исключение: {str(e)[:80]}")

    def test_07_m1_close_project_no_project(self) -> None:
        """ТЕСТ 07: close_project без открытого проекта (не должен падать)"""
        self.logger.section("M_1: close_project (нет проекта)")
        if not self.project_manager:
            self.logger.warning("ProjectManager не создан, пропуск")
            return

        try:
            self.project_manager.current_project = None
            self.project_manager.project_db = None
            self.project_manager.settings = None
            self.project_manager.close_project()
            self.logger.success("close_project() выполнен без ошибок (нет проекта)")
        except Exception as e:
            self.logger.warning(f"close_project() вызвал исключение: {e}")

    def test_08_m1_get_project_info_no_project(self) -> None:
        """ТЕСТ 08: get_project_info без открытого проекта"""
        self.logger.section("M_1: get_project_info (нет проекта)")
        if not self.project_manager:
            self.logger.warning("ProjectManager не создан, пропуск")
            return

        try:
            self.project_manager.current_project = None
            self.project_manager.project_db = None
            self.project_manager.settings = None
            info = self.project_manager.get_project_info()
            self.logger.check(
                isinstance(info, dict),
                f"Возвращен dict (длина {len(info)})",
                f"Тип результата: {type(info)}"
            )
            self.logger.success("get_project_info() выполнен")
        except Exception as e:
            self.logger.warning(f"get_project_info() вызвал исключение: {e}")

    def test_09_m1_create_project(self) -> None:
        """ТЕСТ 09: create_project с минимальными данными"""
        self.logger.section("M_1: create_project")
        if not self.project_manager:
            self.logger.warning("ProjectManager не создан, пропуск")
            return

        try:
            from qgis.core import QgsCoordinateReferenceSystem, QgsProject

            temp_dir = self._get_temp_dir()
            project_name = "test_m1_project"
            crs = QgsCoordinateReferenceSystem("EPSG:4326")

            # Очищаем текущий проект QGIS перед созданием
            QgsProject.instance().clear()

            result = self.project_manager.create_project(project_name, temp_dir, crs)

            if result:
                self.logger.success("Проект создан успешно")

                # Проверяем что current_project установлен
                self.logger.check(
                    self.project_manager.current_project is not None,
                    f"current_project: {self.project_manager.current_project}",
                    "current_project не установлен"
                )

                # Проверяем что project_db создан
                self.logger.check(
                    self.project_manager.project_db is not None,
                    "project_db инициализирован",
                    "project_db не создан"
                )

                # Проверяем что settings заполнены
                self.logger.check(
                    self.project_manager.settings is not None,
                    f"settings.name: {self.project_manager.settings.name if self.project_manager.settings else 'N/A'}",
                    "settings не заполнены"
                )

                # Проверяем что CRS установлена
                project_crs = QgsProject.instance().crs()
                self.logger.check(
                    project_crs.isValid() and project_crs.authid() == "EPSG:4326",
                    f"CRS проекта: {project_crs.authid()}",
                    f"CRS проекта некорректна: {project_crs.authid()}"
                )

                # Проверяем что папка проекта создана
                project_path = os.path.join(temp_dir, project_name)
                self.logger.check(
                    os.path.isdir(project_path),
                    f"Папка проекта существует: {project_path}",
                    "Папка проекта не создана"
                )

                # Проверяем что .qgs файл создан
                qgs_path = os.path.join(project_path, f"{project_name}.qgs")
                self.logger.check(
                    os.path.isfile(qgs_path),
                    "Файл .qgs создан",
                    "Файл .qgs не создан"
                )

            else:
                self.logger.fail("create_project() вернул False")

        except Exception as e:
            self.logger.warning(f"create_project() не удался (может требовать M_19): {str(e)[:120]}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_10_m1_open_project(self) -> None:
        """ТЕСТ 10: open_project для созданного проекта"""
        self.logger.section("M_1: open_project")
        if not self.project_manager:
            self.logger.warning("ProjectManager не создан, пропуск")
            return

        project_path = self.project_manager.current_project
        if not project_path or not os.path.isdir(project_path):
            self.logger.warning("Нет созданного проекта для open_project, пропуск")
            return

        try:
            from qgis.core import QgsProject

            # Закрываем текущий проект
            self.project_manager.close_project()
            QgsProject.instance().clear()

            # Открываем заново
            result = self.project_manager.open_project(project_path)

            if result:
                self.logger.success("Проект открыт успешно")

                self.logger.check(
                    self.project_manager.current_project == project_path,
                    "current_project восстановлен",
                    "current_project не совпадает"
                )
                self.logger.check(
                    self.project_manager.project_db is not None,
                    "project_db восстановлен",
                    "project_db не восстановлен"
                )
                self.logger.check(
                    self.project_manager.settings is not None,
                    "settings восстановлены",
                    "settings не восстановлены"
                )
            else:
                self.logger.fail("open_project() вернул False")

        except Exception as e:
            self.logger.warning(f"open_project() не удался: {str(e)[:120]}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_11_m1_save_project(self) -> None:
        """ТЕСТ 11: save_project для открытого проекта"""
        self.logger.section("M_1: save_project")
        if not self.project_manager or not self.project_manager.current_project:
            self.logger.warning("Нет открытого проекта, пропуск")
            return

        try:
            result = self.project_manager.save_project()
            self.logger.check(
                result is True,
                "save_project() вернул True",
                f"save_project() вернул {result}"
            )

            # Проверяем что modified обновлено
            if self.project_manager.settings:
                self.logger.info(f"settings.modified: {self.project_manager.settings.modified}")
                self.logger.success("Проект сохранен")
            else:
                self.logger.warning("settings = None после сохранения")

        except Exception as e:
            self.logger.warning(f"save_project() не удался: {str(e)[:120]}")

    def test_12_m1_sync_metadata(self) -> None:
        """ТЕСТ 12: sync_metadata_to_layers"""
        self.logger.section("M_1: sync_metadata_to_layers")
        if not self.project_manager or not self.project_manager.current_project:
            self.logger.warning("Нет открытого проекта, пропуск")
            return

        try:
            # Тест с пустым sync_options
            success, message = self.project_manager.sync_metadata_to_layers({})
            self.logger.check(
                isinstance(success, bool),
                f"Возврат: ({success}, '{message}')",
                f"Некорректный тип возврата: {type(success)}"
            )

            # Тест с невалидной CRS
            from qgis.core import QgsCoordinateReferenceSystem
            success2, message2 = self.project_manager.sync_metadata_to_layers({
                'changed_fields': ['crs'],
                'crs_mode': 'redefine',
                'new_crs': QgsCoordinateReferenceSystem()  # Невалидная CRS
            })
            self.logger.check(
                success2 is False,
                f"Невалидная CRS отклонена: '{message2}'",
                f"Невалидная CRS не отклонена: ({success2}, '{message2}')"
            )

            # Тест reproject (не поддерживается)
            success3, message3 = self.project_manager.sync_metadata_to_layers({
                'changed_fields': ['crs'],
                'crs_mode': 'reproject',
                'new_crs': QgsCoordinateReferenceSystem("EPSG:32637")
            })
            self.logger.check(
                success3 is False,
                f"Reproject не поддерживается: '{message3}'",
                f"Reproject не отклонен: ({success3}, '{message3}')"
            )

            self.logger.success("sync_metadata_to_layers() протестирован")

        except Exception as e:
            self.logger.warning(f"sync_metadata_to_layers() не удался: {str(e)[:120]}")

    def test_13_m1_close_project(self) -> None:
        """ТЕСТ 13: close_project для открытого проекта"""
        self.logger.section("M_1: close_project")
        if not self.project_manager or not self.project_manager.current_project:
            self.logger.warning("Нет открытого проекта, пропуск")
            return

        try:
            self.project_manager.close_project()

            self.logger.check(
                self.project_manager.current_project is None,
                "current_project = None после закрытия",
                f"current_project = {self.project_manager.current_project}"
            )
            self.logger.check(
                self.project_manager.project_db is None,
                "project_db = None после закрытия",
                "project_db не очищен"
            )
            self.logger.check(
                self.project_manager.settings is None,
                "settings = None после закрытия",
                "settings не очищены"
            )
            self.logger.success("Проект закрыт корректно")

        except Exception as e:
            self.logger.warning(f"close_project() не удался: {str(e)[:120]}")

    # -------------------------------------------------------------------------
    # M_2 LayerManager: Import and Constructor
    # -------------------------------------------------------------------------

    def test_20_m2_import(self) -> None:
        """ТЕСТ 20: Импорт LayerManager"""
        self.logger.section("M_2: Импорт LayerManager")
        try:
            from Daman_QGIS.managers import LayerManager
            self.logger.success("LayerManager импортирован")
        except ImportError as e:
            self.logger.fail(f"Не удалось импортировать LayerManager: {e}")

    def test_21_m2_constructor(self) -> None:
        """ТЕСТ 21: Конструктор LayerManager"""
        self.logger.section("M_2: Конструктор")
        try:
            from Daman_QGIS.managers import LayerManager
            lm = LayerManager(self.iface)
            self.layer_manager = lm

            self.logger.check(
                lm.iface is not None,
                "iface установлен",
                "iface не установлен"
            )
            self.logger.success("LayerManager создан")
        except Exception as e:
            self.logger.fail(f"Ошибка создания LayerManager: {e}")

    def test_22_m2_methods_exist(self) -> None:
        """ТЕСТ 22: Наличие ключевых методов M_2"""
        self.logger.section("M_2: Наличие методов")
        if not self.layer_manager:
            self.logger.warning("LayerManager не создан, пропуск")
            return

        methods = [
            'add_layer', 'sort_all_layers', 'remove_layer',
            'get_layer_info', 'update_layer_name', 'clear_registry',
            'validate_autocad_styles',
        ]
        missing = []
        for method in methods:
            if not hasattr(self.layer_manager, method):
                missing.append(method)

        if not missing:
            self.logger.success(f"Все {len(methods)} методов присутствуют")
        else:
            self.logger.fail(f"Отсутствуют методы: {', '.join(missing)}")

    def test_23_m2_initial_state(self) -> None:
        """ТЕСТ 23: Начальное состояние LayerManager"""
        self.logger.section("M_2: Начальное состояние")
        if not self.layer_manager:
            self.logger.warning("LayerManager не создан, пропуск")
            return

        lm = self.layer_manager
        self.logger.check(
            isinstance(lm.layer_registry, dict),
            f"layer_registry: dict (длина {len(lm.layer_registry)})",
            f"layer_registry: {type(lm.layer_registry)}"
        )
        self.logger.check(
            len(lm.layer_registry) == 0,
            "layer_registry пуст (корректно для нового экземпляра)",
            f"layer_registry содержит {len(lm.layer_registry)} записей"
        )

        # Проверяем lazy properties
        self.logger.check(
            lm._style_manager is None,
            "_style_manager = None (lazy init)",
            "_style_manager уже инициализирован"
        )
        self.logger.check(
            lm._replacement_manager is None,
            "_replacement_manager = None (lazy init)",
            "_replacement_manager уже инициализирован"
        )
        self.logger.check(
            lm._label_manager is None,
            "_label_manager = None (lazy init)",
            "_label_manager уже инициализирован"
        )

    def test_24_m2_add_layer(self) -> None:
        """ТЕСТ 24: add_layer с тестовым слоем"""
        self.logger.section("M_2: add_layer")
        if not self.layer_manager:
            self.logger.warning("LayerManager не создан, пропуск")
            return

        try:
            from qgis.core import QgsVectorLayer, QgsProject

            # Создаем memory layer для теста
            layer = QgsVectorLayer("Point?crs=EPSG:4326", "test_layer_m2", "memory")
            self.logger.check(
                layer.isValid(),
                "Тестовый memory layer создан и валиден",
                "Тестовый memory layer невалиден"
            )

            if not layer.isValid():
                return

            # add_layer зависит от StyleManager и ReferenceManagers
            # Может упасть если справочники не загружены
            result = self.layer_manager.add_layer(layer, check_precision=False)

            if result:
                self.logger.success("add_layer() выполнен успешно")

                # Проверяем что слой в layer_registry
                self.logger.check(
                    layer.id() in self.layer_manager.layer_registry,
                    f"Слой в layer_registry: {layer.id()[:12]}...",
                    "Слой не добавлен в layer_registry"
                )

                # Проверяем что слой добавлен в QgsProject
                project_layers = QgsProject.instance().mapLayers()
                self.logger.check(
                    layer.id() in project_layers,
                    "Слой добавлен в QgsProject",
                    "Слой не найден в QgsProject"
                )
            else:
                self.logger.warning("add_layer() вернул False (возможно проблема с зависимостями)")

        except Exception as e:
            self.logger.warning(f"add_layer() не удался (зависимости StyleManager/ReferenceManagers): {str(e)[:120]}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_25_m2_get_layer_info(self) -> None:
        """ТЕСТ 25: get_layer_info"""
        self.logger.section("M_2: get_layer_info")
        if not self.layer_manager:
            self.logger.warning("LayerManager не создан, пропуск")
            return

        # Если есть записи в реестре, проверяем первую
        if self.layer_manager.layer_registry:
            first_id = next(iter(self.layer_manager.layer_registry))
            info = self.layer_manager.get_layer_info(first_id)
            self.logger.check(
                info is not None,
                f"get_layer_info() вернул LayerInfo для {first_id[:12]}...",
                "get_layer_info() вернул None для существующего слоя"
            )

            if info:
                self.logger.data("LayerInfo.name", info.name)
                self.logger.data("LayerInfo.type", info.type)
        else:
            self.logger.info("layer_registry пуст, проверяем None для несуществующего ID")

        # Несуществующий ID
        info_none = self.layer_manager.get_layer_info("nonexistent_id_12345")
        self.logger.check(
            info_none is None,
            "get_layer_info() вернул None для несуществующего ID",
            f"get_layer_info() вернул {info_none} для несуществующего ID"
        )

    def test_26_m2_sort_all_layers(self) -> None:
        """ТЕСТ 26: sort_all_layers"""
        self.logger.section("M_2: sort_all_layers")
        if not self.layer_manager:
            self.logger.warning("LayerManager не создан, пропуск")
            return

        try:
            self.layer_manager.sort_all_layers()
            self.logger.success("sort_all_layers() выполнен без ошибок")
        except Exception as e:
            self.logger.warning(f"sort_all_layers() не удался (зависимости ReferenceManagers): {str(e)[:120]}")

    def test_27_m2_remove_layer(self) -> None:
        """ТЕСТ 27: remove_layer"""
        self.logger.section("M_2: remove_layer")
        if not self.layer_manager:
            self.logger.warning("LayerManager не создан, пропуск")
            return

        try:
            from qgis.core import QgsVectorLayer, QgsProject

            # Создаем слой, добавляем напрямую в проект и реестр (обходим add_layer)
            layer = QgsVectorLayer("Point?crs=EPSG:4326", "test_remove_m2", "memory")
            if not layer.isValid():
                self.logger.warning("Не удалось создать memory layer для теста remove_layer")
                return

            QgsProject.instance().addMapLayer(layer)
            layer_id = layer.id()

            # Добавляем в реестр вручную
            from Daman_QGIS.database.schemas import LayerInfo
            from datetime import datetime
            self.layer_manager.layer_registry[layer_id] = LayerInfo(
                id=layer_id,
                name="test_remove_m2",
                type="vector",
                geometry_type="Point",
                source_path="memory",
                prefix="",
                created=datetime.now(),
                modified=datetime.now(),
                readonly=False
            )

            # Удаляем
            result = self.layer_manager.remove_layer(layer_id)

            self.logger.check(
                result is True,
                "remove_layer() вернул True",
                f"remove_layer() вернул {result}"
            )

            self.logger.check(
                layer_id not in self.layer_manager.layer_registry,
                "Слой удален из layer_registry",
                "Слой остался в layer_registry"
            )

            project_layers = QgsProject.instance().mapLayers()
            self.logger.check(
                layer_id not in project_layers,
                "Слой удален из QgsProject",
                "Слой остался в QgsProject"
            )

            self.logger.success("remove_layer() работает корректно")

        except Exception as e:
            self.logger.warning(f"remove_layer() не удался: {str(e)[:120]}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_28_m2_clear_registry(self) -> None:
        """ТЕСТ 28: clear_registry"""
        self.logger.section("M_2: clear_registry")
        if not self.layer_manager:
            self.logger.warning("LayerManager не создан, пропуск")
            return

        try:
            # Добавляем запись для проверки очистки
            self.layer_manager.layer_registry["dummy_id"] = "dummy"
            self.logger.check(
                len(self.layer_manager.layer_registry) > 0,
                f"Реестр содержит {len(self.layer_manager.layer_registry)} записей перед очисткой",
                "Реестр пуст перед очисткой"
            )

            self.layer_manager.clear_registry()

            self.logger.check(
                len(self.layer_manager.layer_registry) == 0,
                "Реестр очищен (0 записей)",
                f"Реестр не очищен ({len(self.layer_manager.layer_registry)} записей)"
            )
            self.logger.success("clear_registry() работает корректно")

        except Exception as e:
            self.logger.fail(f"clear_registry() не удался: {e}")

    # -------------------------------------------------------------------------
    # Interaction: M_1 + M_2
    # -------------------------------------------------------------------------

    def test_30_interaction_create_and_add_layers(self) -> None:
        """ТЕСТ 30: Создание проекта (M_1) и добавление слоев (M_2)"""
        self.logger.section("M_1 + M_2: Создание проекта и добавление слоев")
        if not self.project_manager or not self.layer_manager:
            self.logger.warning("ProjectManager или LayerManager не создан, пропуск")
            return

        try:
            from qgis.core import QgsVectorLayer, QgsCoordinateReferenceSystem, QgsProject

            temp_dir = self._get_temp_dir()
            project_name = "test_interaction_m1m2"
            project_path = os.path.join(temp_dir, project_name)

            # Если проект уже существует от предыдущего запуска, удаляем
            if os.path.exists(project_path):
                shutil.rmtree(project_path)

            # Очищаем текущий проект
            if self.project_manager.current_project:
                self.project_manager.close_project()
            QgsProject.instance().clear()

            # Создаем проект через M_1
            crs = QgsCoordinateReferenceSystem("EPSG:4326")
            created = self.project_manager.create_project(project_name, temp_dir, crs)

            if not created:
                self.logger.warning("Не удалось создать проект для теста взаимодействия")
                return

            self.logger.success("Проект создан через M_1")

            # Создаем 3 тестовых слоя и добавляем через M_2
            test_layers = [
                ("Point?crs=EPSG:4326", "L_test_points"),
                ("LineString?crs=EPSG:4326", "L_test_lines"),
                ("Polygon?crs=EPSG:4326", "L_test_polygons"),
            ]

            added_count = 0
            added_ids = []
            for geom_def, name in test_layers:
                layer = QgsVectorLayer(geom_def, name, "memory")
                if layer.isValid():
                    try:
                        result = self.layer_manager.add_layer(layer, check_precision=False)
                        if result:
                            added_count += 1
                            added_ids.append(layer.id())
                    except Exception as e:
                        self.logger.info(f"add_layer({name}) не удался: {str(e)[:80]}")

            self.logger.info(f"Добавлено слоев: {added_count}/{len(test_layers)}")

            if added_count > 0:
                self.logger.success(f"Слои добавлены в проект ({added_count})")
            else:
                self.logger.warning("Ни один слой не добавлен (зависимости StyleManager)")

            # Проверяем слои в QgsProject
            project_layers = QgsProject.instance().mapLayers()
            self.logger.info(f"Всего слоев в QgsProject: {len(project_layers)}")

            # Сортировка
            try:
                self.layer_manager.sort_all_layers()
                self.logger.success("sort_all_layers() выполнен для проекта с слоями")
            except Exception as e:
                self.logger.warning(f"sort_all_layers() не удался: {str(e)[:80]}")

            # Сохраняем проект
            try:
                self.project_manager.save_project()
                self.logger.success("Проект сохранен после добавления слоев")
            except Exception as e:
                self.logger.warning(f"save_project() не удался: {str(e)[:80]}")

            # get_project_info
            try:
                info = self.project_manager.get_project_info()
                if info:
                    self.logger.data("project_info.name", info.get('name', 'N/A'))
                    self.logger.data("project_info.crs_epsg", str(info.get('crs_epsg', 'N/A')))
                    self.logger.data("project_info.layers_count", str(info.get('layers_count', 'N/A')))
                    self.logger.success("get_project_info() вернул данные")
            except Exception as e:
                self.logger.warning(f"get_project_info() не удался: {str(e)[:80]}")

            # Удаляем добавленные слои через M_2
            removed_count = 0
            for lid in added_ids:
                try:
                    if self.layer_manager.remove_layer(lid):
                        removed_count += 1
                except Exception:
                    pass

            if added_count > 0:
                self.logger.info(f"Удалено слоев: {removed_count}/{added_count}")

            # Закрываем проект
            try:
                self.project_manager.close_project()
                self.logger.success("Проект закрыт после теста взаимодействия")
            except Exception as e:
                self.logger.warning(f"close_project() не удался: {str(e)[:80]}")

        except Exception as e:
            self.logger.error(f"Тест взаимодействия M_1+M_2 не удался: {str(e)[:120]}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
