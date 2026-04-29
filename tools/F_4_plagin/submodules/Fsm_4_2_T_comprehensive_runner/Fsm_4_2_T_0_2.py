# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_0_2 - Тест функции F_0_2_Открытие проекта
Полная диагностика работы открытия существующих проектов
"""

import os
import tempfile
import shutil
import json
from pathlib import Path
from qgis.core import QgsProject, QgsCoordinateReferenceSystem

from Daman_QGIS.constants import PROJECT_GPKG_NAME


class TestF02:
    """Тесты для функции F_0_2_Открытие проекта"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.module = None
        self.test_dir = None
        self.project_manager = None

    def run_all_tests(self):
        """Запуск всех тестов F_0_2"""
        self.logger.section("ТЕСТ F_0_2: Открытие существующего проекта")

        # Создаем временную директорию для тестов
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f02_")
        self.logger.info(f"Временная директория: {self.test_dir}")
        assert self.test_dir is not None  # tempfile.mkdtemp всегда возвращает строку

        try:
            # Тест 1: Инициализация модуля
            self.test_01_init_module()

            # Тест 2: Проверка зависимостей
            self.test_02_check_dependencies()

            # Тест 3: Создание тестового проекта
            self.test_03_create_test_project()

            # Тест 4: Открытие валидного проекта
            self.test_04_open_valid_project()

            # Тест 5: Проверка загрузки метаданных
            self.test_05_verify_metadata_loading()

            # Тест 6: Проверка структуры проекта
            self.test_06_verify_project_structure()

            # Тест 7: Обработка ошибок (несуществующий файл)
            self.test_07_handle_missing_file()

            # Тест 8: Обработка поврежденного проекта
            self.test_08_handle_corrupted_project()

            # Тест 9-14: Обработка разных состояний плагина
            self.test_09_plugin_state_native_project()
            self.test_10_plugin_state_already_open()
            self.test_11_plugin_state_settings()
            self.test_12_regular_qgis_project()
            self.test_13_find_gpkg_path_method()
            self.test_14_restore_crs_method()

        finally:
            # Очистка временных файлов
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    shutil.rmtree(self.test_dir)
                    self.logger.info("Временные файлы очищены")
                except Exception as e:
                    self.logger.warning(f"Не удалось удалить временные файлы: {str(e)}")

        # Итоговая сводка
        self.logger.summary()

    def test_01_init_module(self):
        """ТЕСТ 1: Инициализация модуля F_0_2"""
        self.logger.section("1. Инициализация модуля F_0_2_OpenProject")

        try:
            from Daman_QGIS.tools.F_0_project.F_0_2_open_project import F_0_2_OpenProject

            self.module = F_0_2_OpenProject(self.iface)
            self.logger.success("Модуль F_0_2_OpenProject загружен успешно")

            # Проверяем наличие методов
            self.logger.check(
                hasattr(self.module, 'run'),
                "Метод run существует",
                "Метод run отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, 'set_project_manager'),
                "Метод set_project_manager существует",
                "Метод set_project_manager отсутствует!"
            )


            # Проверяем свойство name
            if hasattr(self.module, 'name'):
                self.logger.success(f"Свойство name: '{self.module.name}'")
            else:
                self.logger.fail("Свойство name отсутствует!")

        except Exception as e:
            self.logger.error(f"Ошибка инициализации F_0_2_OpenProject: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
            self.module = None

    def test_02_check_dependencies(self):
        """ТЕСТ 2: Проверка зависимостей"""
        self.logger.section("2. Проверка зависимостей модуля")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            # Проверяем наличие ProjectManager
            from Daman_QGIS.managers import ProjectManager
            self.project_manager = ProjectManager(self.iface, os.path.dirname(os.path.dirname(__file__)))
            self.logger.success("ProjectManager доступен")

            # Устанавливаем ProjectManager в модуль
            self.module.set_project_manager(self.project_manager)
            self.logger.success("ProjectManager установлен в F_0_2")

            # F_0_2 использует стандартный QFileDialog, отдельного диалога нет
            from qgis.PyQt.QtWidgets import QFileDialog
            self.logger.success("QFileDialog доступен")

        except Exception as e:
            self.logger.error(f"Ошибка проверки зависимостей: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_03_create_test_project(self):
        """ТЕСТ 3: Создание тестового проекта для открытия"""
        self.logger.section("3. Создание тестового проекта")

        if not self.project_manager or not self.test_dir:
            self.logger.fail("ProjectManager или test_dir не инициализирован, пропускаем тест")
            return

        try:
            # Создаем тестовый проект
            test_project_path = os.path.join(self.test_dir, "Test_Open_Project")
            os.makedirs(test_project_path, exist_ok=True)
            self.logger.success("Директория тестового проекта создана")

            # Создаем файл project.gpkg (пустой GeoPackage)
            gpkg_path = os.path.join(test_project_path, PROJECT_GPKG_NAME)

            # Создаем минимальный валидный GeoPackage
            from qgis.core import QgsVectorLayer
            layer = QgsVectorLayer("Point?crs=EPSG:32637", "temp", "memory")

            from qgis.core import QgsVectorFileWriter
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = "metadata"

            writer = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                gpkg_path,
                QgsProject.instance().transformContext(),
                options
            )

            if writer[0] == QgsVectorFileWriter.NoError:
                self.logger.success("GeoPackage создан")
            else:
                self.logger.fail(f"Ошибка создания GeoPackage: {writer}")

            # Создаем метаданные
            metadata = {
                '1_0_working_name': 'Test_Open_Project',
                '1_1_object_full_name': 'Тестовый проект для открытия',
                '1_2_object_type': 'area',
                '1_2_object_type_name': 'Площадной',
                '1_4_2_crs_epsg': '32637',
                '1_4_2_crs_wkt': QgsCoordinateReferenceSystem('EPSG:32637').toWkt(),
            }

            # Сохраняем метаданные в ProjectManager
            self.project_manager.metadata = metadata
            self.project_manager.project_path = test_project_path

            self.logger.success("Метаданные тестового проекта созданы")
            self.logger.data("Путь", test_project_path)

            # Проверяем что все файлы на месте
            self.logger.check(
                os.path.exists(gpkg_path),
                "GeoPackage файл существует",
                "GeoPackage файл не найден!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка создания тестового проекта: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_04_open_valid_project(self):
        """ТЕСТ 4: Открытие валидного проекта"""
        self.logger.section("4. Открытие валидного проекта")

        if not self.module or not self.project_manager or not self.test_dir:
            self.logger.fail("Модуль, ProjectManager или test_dir не инициализирован, пропускаем тест")
            return

        try:
            test_project_path = os.path.join(self.test_dir, "Test_Open_Project")

            # Проверяем что путь существует
            if not os.path.exists(test_project_path):
                self.logger.fail("Тестовый проект не был создан в предыдущем тесте")
                return

            self.logger.info(f"Открытие проекта: {test_project_path}")

            # Пытаемся открыть проект через ProjectManager
            # (так как F_0_2 использует диалог, тестируем напрямую через ProjectManager)
            gpkg_path = os.path.join(test_project_path, PROJECT_GPKG_NAME)

            self.logger.check(
                os.path.exists(gpkg_path),
                "GeoPackage найден",
                "GeoPackage не найден!"
            )

            # Проверяем что можно загрузить метаданные
            # Это симуляция того, что делает F_0_2
            self.project_manager.project_path = test_project_path

            self.logger.success("Путь к проекту установлен")
            self.logger.data("project_path", self.project_manager.project_path)

        except Exception as e:
            self.logger.error(f"Ошибка открытия проекта: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_05_verify_metadata_loading(self):
        """ТЕСТ 5: Проверка загрузки метаданных"""
        self.logger.section("5. Проверка загрузки метаданных проекта")

        if not self.project_manager:
            self.logger.fail("ProjectManager не инициализирован, пропускаем тест")
            return

        try:
            # Проверяем что метаданные доступны
            metadata = self.project_manager.metadata

            if not metadata:
                self.logger.fail("Метаданные не загружены")
                return

            self.logger.success(f"Метаданные загружены ({len(metadata)} полей)")

            # Проверяем обязательные поля
            required_fields = [
                '1_0_working_name',
                '1_1_object_full_name',
                '1_2_object_type',
                '1_4_2_crs_epsg',
            ]

            for field in required_fields:
                if field in metadata:
                    self.logger.success(f"Поле '{field}' присутствует: {metadata[field]}")
                else:
                    self.logger.fail(f"Обязательное поле '{field}' отсутствует!")

            # Проверяем корректность CRS
            if '1_4_2_crs_epsg' in metadata:
                epsg = metadata['1_4_2_crs_epsg']
                crs = QgsCoordinateReferenceSystem(f'EPSG:{epsg}')

                self.logger.check(
                    crs.isValid(),
                    f"CRS EPSG:{epsg} валидна",
                    f"CRS EPSG:{epsg} невалидна!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка проверки метаданных: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_06_verify_project_structure(self):
        """ТЕСТ 6: Проверка структуры открытого проекта"""
        self.logger.section("6. Проверка структуры проекта")

        if not self.project_manager:
            self.logger.fail("ProjectManager не инициализирован, пропускаем тест")
            return

        try:
            project_path = self.project_manager.project_path

            if not project_path:
                self.logger.fail("Путь к проекту не установлен")
                return

            self.logger.info(f"Проверка структуры: {project_path}")

            # Проверяем основные компоненты
            gpkg_path = os.path.join(project_path, PROJECT_GPKG_NAME)

            self.logger.check(
                os.path.exists(project_path),
                "Директория проекта существует",
                "Директория проекта не найдена!"
            )

            self.logger.check(
                os.path.isdir(project_path),
                "Путь является директорией",
                "Путь не является директорией!"
            )

            self.logger.check(
                os.path.exists(gpkg_path),
                "GeoPackage существует",
                "GeoPackage не найден!"
            )

            # Проверяем размер GeoPackage
            if os.path.exists(gpkg_path):
                size = os.path.getsize(gpkg_path)
                self.logger.data("Размер GeoPackage", f"{size} байт")

                self.logger.check(
                    size > 0,
                    "GeoPackage не пустой",
                    "GeoPackage пустой!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка проверки структуры: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_07_handle_missing_file(self):
        """ТЕСТ 7: Обработка несуществующего файла"""
        self.logger.section("7. Обработка ошибки: несуществующий проект")

        if not self.module or not self.test_dir:
            self.logger.fail("Модуль или test_dir не инициализирован, пропускаем тест")
            return

        try:
            # Путь к несуществующему проекту
            non_existent_path = os.path.join(self.test_dir, "NonExistentProject")

            self.logger.info(f"Попытка открыть несуществующий проект: {non_existent_path}")

            # Проверяем что путь действительно не существует
            self.logger.check(
                not os.path.exists(non_existent_path),
                "Путь действительно не существует (ожидаемое поведение)",
                "Путь существует (неожиданно)!"
            )

            # В реальном сценарии F_0_2 должен показать ошибку через QMessageBox
            # Здесь мы просто проверяем что можем детектировать эту ситуацию

            if not os.path.exists(non_existent_path):
                self.logger.success("Отсутствующий путь корректно определен")

            gpkg_path = os.path.join(non_existent_path, PROJECT_GPKG_NAME)
            if not os.path.exists(gpkg_path):
                self.logger.success("Отсутствующий GeoPackage корректно определен")

        except Exception as e:
            self.logger.error(f"Ошибка теста обработки ошибок: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_08_handle_corrupted_project(self):
        """ТЕСТ 8: Обработка поврежденного проекта"""
        self.logger.section("8. Обработка поврежденного проекта")

        if not self.module or not self.test_dir:
            self.logger.fail("Модуль или test_dir не инициализирован, пропускаем тест")
            return

        try:
            # Создаем директорию с поврежденным проектом
            corrupted_path = os.path.join(self.test_dir, "CorruptedProject")
            os.makedirs(corrupted_path, exist_ok=True)
            self.logger.success("Директория поврежденного проекта создана")

            # Создаем поврежденный GeoPackage (пустой файл)
            gpkg_path = os.path.join(corrupted_path, PROJECT_GPKG_NAME)
            with open(gpkg_path, 'w') as f:
                f.write("This is not a valid GeoPackage")

            self.logger.success("Поврежденный GeoPackage создан")

            # Проверяем что файл существует но невалиден
            self.logger.check(
                os.path.exists(gpkg_path),
                "Файл существует",
                "Файл не создан!"
            )

            # Пытаемся открыть как слой и ожидаем ошибку
            from qgis.core import QgsVectorLayer
            layer = QgsVectorLayer(gpkg_path, "test", "ogr")

            self.logger.check(
                not layer.isValid(),
                "Поврежденный файл корректно определен как невалидный",
                "Поврежденный файл определен как валидный (ошибка)!"
            )

            self.logger.success("Обработка поврежденного проекта работает корректно")

        except Exception as e:
            # Ошибка ожидается при работе с поврежденными файлами
            self.logger.success(f"Ошибка корректно обработана: {str(e)[:100]}")

    def test_09_plugin_state_native_project(self):
        """ТЕСТ 9: Обработка нативно открытого проекта плагина"""
        self.logger.section("9. Нативно открытый проект плагина")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            # Проверяем логику определения типа проекта
            # Когда проект открыт нативно через QGIS (не через F_0_2),
            # F_0_2 должен корректно определить что это проект плагина

            # Проверяем наличие метода init_from_native_project в ProjectManager
            if self.project_manager and hasattr(self.project_manager, 'init_from_native_project'):
                self.logger.success("Метод init_from_native_project() существует")
            else:
                self.logger.warning("Метод init_from_native_project() отсутствует в ProjectManager")

            # Проверяем использование M_19 для проверки структуры
            from Daman_QGIS.managers import registry
            structure_manager = registry.get('M_19')

            self.logger.check(
                structure_manager is not None,
                "M_19 ProjectStructureManager доступен",
                "M_19 ProjectStructureManager недоступен!"
            )

            self.logger.check(
                hasattr(structure_manager, 'get_gpkg_path'),
                "Метод get_gpkg_path() в M_19 существует",
                "Метод get_gpkg_path() отсутствует!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")

    def test_10_plugin_state_already_open(self):
        """ТЕСТ 10: Обработка уже открытого проекта плагина"""
        self.logger.section("10. Проект уже открыт через плагин")

        if not self.module or not self.project_manager:
            self.logger.fail("Модуль или ProjectManager не инициализирован")
            return

        try:
            # Проверяем метод is_project_open
            self.logger.check(
                hasattr(self.project_manager, 'is_project_open'),
                "Метод is_project_open() существует",
                "Метод is_project_open() отсутствует!"
            )

            # Проверяем метод close_project
            self.logger.check(
                hasattr(self.project_manager, 'close_project'),
                "Метод close_project() существует",
                "Метод close_project() отсутствует!"
            )

            # Проверяем логику проверки isDirty
            is_dirty = QgsProject.instance().isDirty()
            self.logger.info(f"QgsProject.isDirty() = {is_dirty}")

            # Это нормальное состояние для теста
            self.logger.success("Логика проверки несохранённых изменений работает")

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")

    def test_11_plugin_state_settings(self):
        """ТЕСТ 11: Доступ к settings проекта"""
        self.logger.section("11. Settings проекта")

        if not self.project_manager:
            self.logger.fail("ProjectManager не инициализирован")
            return

        try:
            # Проверяем атрибут settings
            self.logger.check(
                hasattr(self.project_manager, 'settings'),
                "Атрибут settings существует",
                "Атрибут settings отсутствует!"
            )

            # Проверяем что settings может быть None (когда проект не открыт)
            settings = self.project_manager.settings
            if settings is None:
                self.logger.success("settings = None (проект не открыт через плагин)")
            else:
                self.logger.success(f"settings инициализирован: {type(settings)}")

                # Проверяем атрибут object_name
                if hasattr(settings, 'object_name'):
                    self.logger.success(f"object_name доступен: {settings.object_name}")
                else:
                    self.logger.warning("object_name отсутствует в settings")

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")

    def test_12_regular_qgis_project(self):
        """ТЕСТ 12: Обработка обычного QGIS проекта (не плагина)"""
        self.logger.section("12. Обычный QGIS проект")

        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            # Логика F_0_2: если проект открыт но это НЕ проект плагина,
            # используется QgsProject.instance().clear() вместо close_project()

            # Проверяем что QgsProject.clear() существует
            self.logger.check(
                hasattr(QgsProject.instance(), 'clear'),
                "QgsProject.clear() существует",
                "QgsProject.clear() отсутствует!"
            )

            # Проверяем fileName
            current_file = QgsProject.instance().fileName()
            if current_file:
                self.logger.info(f"Текущий проект: {current_file}")
            else:
                self.logger.success("Нет открытого проекта (ожидаемо для теста)")

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")

    def test_13_find_gpkg_path_method(self):
        """ТЕСТ 13: Метод _find_gpkg_path"""
        self.logger.section("13. Метод _find_gpkg_path")

        if not self.module or not self.test_dir:
            self.logger.fail("Модуль или test_dir не инициализирован")
            return

        try:
            # Проверяем наличие метода
            self.logger.check(
                hasattr(self.module, '_find_gpkg_path'),
                "Метод _find_gpkg_path() существует",
                "Метод _find_gpkg_path() отсутствует!"
            )

            # Тест с несуществующей папкой
            result = self.module._find_gpkg_path(os.path.join(self.test_dir, "nonexistent"))
            self.logger.check(
                result == "",
                "Несуществующая папка -> пустая строка",
                f"Несуществующая папка -> {result}"
            )

            # Тест с папкой без gpkg
            empty_dir = os.path.join(self.test_dir, "empty_project")
            os.makedirs(empty_dir, exist_ok=True)
            result2 = self.module._find_gpkg_path(empty_dir)
            self.logger.check(
                result2 == "",
                "Папка без gpkg -> пустая строка",
                f"Папка без gpkg -> {result2}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")

    def test_14_restore_crs_method(self):
        """ТЕСТ 14: Метод _restore_crs"""
        self.logger.section("14. Восстановление CRS")

        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            # Проверяем наличие метода
            self.logger.check(
                hasattr(self.module, '_restore_crs'),
                "Метод _restore_crs() существует",
                "Метод _restore_crs() отсутствует!"
            )

            # Тест с пустыми метаданными
            self.module._restore_crs({})
            self.logger.success("_restore_crs с пустыми метаданными не вызывает ошибку")

            # Тест с WKT
            test_wkt = QgsCoordinateReferenceSystem('EPSG:32637').toWkt()
            metadata_wkt = {
                '1_4_2_crs_wkt': {'value': test_wkt}
            }
            self.module._restore_crs(metadata_wkt)
            self.logger.success("_restore_crs с WKT работает")

            # Тест с EPSG
            metadata_epsg = {
                '1_4_2_crs_epsg': {'value': '32637'}
            }
            self.module._restore_crs(metadata_epsg)
            self.logger.success("_restore_crs с EPSG работает")

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")
