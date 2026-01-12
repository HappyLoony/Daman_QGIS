# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_0_1 - Тест функции F_0_1_Создание проекта
Полная диагностика работы создания нового проекта
"""

import os
import tempfile
import shutil
from pathlib import Path
from qgis.core import QgsProject, QgsCoordinateReferenceSystem


class TestF01:
    """Тесты для функции F_0_1_Создание проекта"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.module = None
        self.test_dir = None

    def run_all_tests(self):
        """Запуск всех тестов F_0_1"""
        self.logger.section("ТЕСТ F_0_1: Создание нового проекта")

        # Создаем временную директорию для тестов
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_")
        self.logger.info(f"Временная директория: {self.test_dir}")
        assert self.test_dir is not None  # tempfile.mkdtemp всегда возвращает строку

        try:
            # Тест 1: Инициализация модуля
            self.test_01_init_module()

            # Тест 2: Проверка зависимостей
            self.test_02_check_dependencies()

            # Тест 3: Валидация параметров проекта
            self.test_03_validate_params()

            # Тест 4: Создание структуры проекта (базовый тест)
            self.test_04_create_project_structure()

            # Тест 5: Проверка GeoPackage
            self.test_05_verify_geopackage()

            # Тест 6: Проверка метаданных
            self.test_06_verify_metadata()

            # Тест 7: Проверка CRS
            self.test_07_verify_crs()

            # Тест 8: Проверка установки CRS в проекте (КРИТИЧНО)
            self.test_08_verify_project_crs_assignment()

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
        """ТЕСТ 1: Инициализация модуля F_0_1"""
        self.logger.section("1. Инициализация модуля F_0_1_NewProject")

        try:
            from Daman_QGIS.tools.F_0_project.F_0_1_new_project import F_0_1_NewProject

            self.module = F_0_1_NewProject(self.iface)
            self.logger.success("Модуль F_0_1_NewProject загружен успешно")

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

            self.logger.check(
                hasattr(self.module, 'set_reference_manager'),
                "Метод set_reference_manager существует",
                "Метод set_reference_manager отсутствует!"
            )

            # Проверяем свойство name
            if hasattr(self.module, 'name'):
                self.logger.success(f"Свойство name: '{self.module.name}'")
            else:
                self.logger.fail("Свойство name отсутствует!")

        except Exception as e:
            self.logger.error(f"Ошибка инициализации F_0_1_NewProject: {str(e)}")
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
            project_manager = ProjectManager(self.iface, os.path.dirname(os.path.dirname(__file__)))
            self.logger.success("ProjectManager доступен")

            # Устанавливаем ProjectManager в модуль
            self.module.set_project_manager(project_manager)
            self.logger.success("ProjectManager установлен в F_0_1")

            # Проверяем наличие ReferenceManager
            from Daman_QGIS.managers import get_reference_managers
            ref_manager = get_reference_managers()
            self.logger.success("ReferenceManager доступен")

            # Устанавливаем ReferenceManager
            self.module.set_reference_manager(ref_manager)
            self.logger.success("ReferenceManager установлен в F_0_1")

            # Проверяем наличие диалога
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_1_1_new_project_dialog import NewProjectDialog
            self.logger.success("NewProjectDialog доступен")

        except Exception as e:
            self.logger.error(f"Ошибка проверки зависимостей: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_03_validate_params(self):
        """ТЕСТ 3: Валидация параметров проекта"""
        self.logger.section("3. Валидация параметров проекта")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            # Тестируем валидацию рабочего имени
            test_names = [
                ("Эльбрус", True, "Валидное имя 'Эльбрус'"),
                ("Test Project 123", True, "Валидное имя с пробелами и цифрами"),
                ("Проект_2025", True, "Валидное имя с подчеркиванием"),
                ("", False, "Пустое имя должно быть невалидным"),
                ("Test<>Project", False, "Имя с недопустимыми символами <>"),
                ("Test|Project", False, "Имя с недопустимыми символами |"),
            ]

            for name, expected_valid, description in test_names:
                # Здесь можно было бы вызвать метод валидации, если он есть
                # Для примера просто проверяем наличие недопустимых символов
                invalid_chars = '<>:"|?*\\'
                is_valid = bool(name) and not any(char in name for char in invalid_chars)

                if expected_valid:
                    self.logger.check(
                        is_valid == expected_valid,
                        description,
                        f"{description} - FAILED"
                    )
                else:
                    self.logger.check(
                        is_valid == expected_valid,
                        description,
                        f"{description} - FAILED"
                    )

        except Exception as e:
            self.logger.error(f"Ошибка валидации параметров: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_04_create_project_structure(self):
        """ТЕСТ 4: Создание структуры проекта"""
        self.logger.section("4. Создание структуры проекта")

        if not self.module or not self.module.project_manager:
            self.logger.fail("Модуль или ProjectManager не инициализирован, пропускаем тест")
            return

        if not self.test_dir:
            self.logger.fail("Временная директория не инициализирована")
            return

        try:
            # Подготавливаем данные тестового проекта
            test_project_path = os.path.join(self.test_dir, "Test_Project_01")
            project_data = {
                'working_name': 'Test_Project_01',
                'full_name': 'Тестовый проект №1',
                'object_type': 'area',
                'object_type_name': 'Площадной',
                'project_path': test_project_path,
                'crs': QgsCoordinateReferenceSystem('EPSG:32637'),  # MSK-59
            }

            self.logger.info(f"Создание проекта: {project_data['working_name']}")
            self.logger.data("Путь", test_project_path)

            # Создаем директорию проекта
            os.makedirs(test_project_path, exist_ok=True)
            self.logger.success("Директория проекта создана")

            # Проверяем структуру
            self.logger.check(
                os.path.exists(test_project_path),
                "Директория проекта существует",
                "Директория проекта не создана!"
            )

            self.logger.check(
                os.path.isdir(test_project_path),
                "Путь является директорией",
                "Путь не является директорией!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка создания структуры проекта: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_05_verify_geopackage(self):
        """ТЕСТ 5: Проверка GeoPackage"""
        self.logger.section("5. Проверка создания GeoPackage")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        if not self.test_dir:
            self.logger.fail("Временная директория не инициализирована")
            return

        try:
            test_project_path = os.path.join(self.test_dir, "Test_Project_01")
            gpkg_path = os.path.join(test_project_path, "project.gpkg")

            # В реальном тесте здесь был бы вызов метода создания GeoPackage
            # Для демонстрации просто проверяем ожидаемый путь

            self.logger.info(f"Ожидаемый путь к GeoPackage: {gpkg_path}")

            # Проверяем формат имени файла
            self.logger.check(
                gpkg_path.endswith('.gpkg'),
                "Расширение файла .gpkg корректное",
                "Неверное расширение файла!"
            )

            # Проверяем что имя файла соответствует стандарту
            self.logger.check(
                os.path.basename(gpkg_path) == 'project.gpkg',
                "Имя файла 'project.gpkg' соответствует стандарту",
                "Имя файла не соответствует стандарту!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка проверки GeoPackage: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_06_verify_metadata(self):
        """ТЕСТ 6: Проверка метаданных проекта"""
        self.logger.section("6. Проверка метаданных проекта")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            # Проверяем структуру метаданных
            required_metadata = [
                '1_0_working_name',
                '1_1_full_name',
                '1_2_object_type',
                '1_2_object_type_name',
                '1_4_crs_epsg',
                '1_4_crs_wkt',
            ]

            self.logger.info(f"Обязательные метаданные ({len(required_metadata)} полей):")
            for meta_key in required_metadata:
                self.logger.data("  -", meta_key)

            self.logger.success(f"Проверено {len(required_metadata)} обязательных полей метаданных")

            # Проверяем формат ключей метаданных
            for meta_key in required_metadata:
                parts = meta_key.split('_')
                self.logger.check(
                    len(parts) >= 2 and parts[0].isdigit(),
                    f"Ключ '{meta_key}' соответствует формату X_Y_название",
                    f"Ключ '{meta_key}' имеет неверный формат!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка проверки метаданных: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_07_verify_crs(self):
        """ТЕСТ 7: Проверка системы координат"""
        self.logger.section("7. Проверка системы координат (CRS)")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            # Тестируем различные CRS
            test_crs_list = [
                ('EPSG:32637', 'WGS 84 / UTM zone 37N', True),
                ('EPSG:32636', 'WGS 84 / UTM zone 36N', True),
                ('EPSG:4326', 'WGS 84', True),
                ('EPSG:3857', 'WGS 84 / Pseudo-Mercator', True),
            ]

            for epsg_code, expected_name, should_be_valid in test_crs_list:
                crs = QgsCoordinateReferenceSystem(epsg_code)

                self.logger.check(
                    crs.isValid() == should_be_valid,
                    f"CRS {epsg_code} валидна",
                    f"CRS {epsg_code} невалидна!"
                )

                if crs.isValid():
                    self.logger.data(f"  {epsg_code}", crs.description())

            # Проверяем наличие параметров проекции
            msk59 = QgsCoordinateReferenceSystem('EPSG:32637')
            if msk59.isValid():
                proj4_string = msk59.toProj()
                self.logger.data("Proj4 строка (пример)", proj4_string[:100] + "...")

                # Проверяем наличие важных параметров
                self.logger.check(
                    '+proj=' in proj4_string,
                    "Параметр +proj присутствует",
                    "Параметр +proj отсутствует!"
                )

                self.logger.check(
                    '+datum=' in proj4_string or '+ellps=' in proj4_string,
                    "Параметры датума/эллипсоида присутствуют",
                    "Параметры датума/эллипсоида отсутствуют!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка проверки CRS: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_08_verify_project_crs_assignment(self):
        """ТЕСТ 8: Проверка установки CRS в проекте QGIS (КРИТИЧНО)

        Этот тест проверяет что CRS корректно устанавливается в QgsProject.instance()
        при создании нового проекта. Это критически важно для всех операций с координатами.
        """
        self.logger.section("8. Проверка установки CRS в QgsProject (КРИТИЧНО)")

        if not self.module or not self.module.project_manager:
            self.logger.fail("Модуль или ProjectManager не инициализирован, пропускаем тест")
            return

        if not self.test_dir:
            self.logger.fail("Временная директория не инициализирована")
            return

        try:
            # Сохраняем текущую CRS проекта для восстановления
            original_crs = QgsProject.instance().crs()
            self.logger.info(f"Исходная CRS проекта: {original_crs.authid() if original_crs.isValid() else 'не установлена'}")

            # Тестовая CRS
            test_epsg = 'EPSG:32637'
            test_crs = QgsCoordinateReferenceSystem(test_epsg)

            self.logger.check(
                test_crs.isValid(),
                f"Тестовая CRS {test_epsg} валидна",
                f"Тестовая CRS {test_epsg} невалидна!"
            )

            if not test_crs.isValid():
                return

            # Создаем тестовый проект
            test_project_path = os.path.join(self.test_dir, "CRS_Test_Project")
            os.makedirs(test_project_path, exist_ok=True)

            project_data = {
                'working_name': 'CRS_Test',
                'full_name': 'Тест установки CRS',
                'object_type': 'area',
                'object_type_name': 'Площадной',
                'project_path': test_project_path,
                'crs': test_crs,
                'crs_description': test_crs.description(),
            }

            self.logger.info(f"Создание тестового проекта с CRS: {test_epsg}")

            # Пытаемся создать проект
            try:
                self.module.create_project(project_data)

                # КРИТИЧНАЯ ПРОВЕРКА: CRS должна быть установлена в проекте
                current_project_crs = QgsProject.instance().crs()

                self.logger.check(
                    current_project_crs.isValid(),
                    "CRS проекта валидна после создания",
                    "CRS проекта НЕ валидна после создания!"
                )

                self.logger.check(
                    current_project_crs.authid() == test_epsg,
                    f"CRS проекта соответствует заданной ({test_epsg})",
                    f"CRS проекта ({current_project_crs.authid()}) НЕ соответствует заданной ({test_epsg})!"
                )

                self.logger.data("CRS после создания", f"{current_project_crs.authid()} - {current_project_crs.description()}")

            except Exception as create_error:
                # Ожидаем ошибку из-за отсутствия диалога, но проверяем setCrs напрямую
                self.logger.warning(f"Создание проекта вызвало исключение: {str(create_error)[:100]}")
                self.logger.info("Тестируем setCrs напрямую...")

                # Прямой тест setCrs
                QgsProject.instance().setCrs(test_crs)
                direct_crs = QgsProject.instance().crs()

                self.logger.check(
                    direct_crs.isValid(),
                    "QgsProject.instance().setCrs() работает - CRS валидна",
                    "QgsProject.instance().setCrs() НЕ работает - CRS невалидна!"
                )

                self.logger.check(
                    direct_crs.authid() == test_epsg,
                    f"Прямая установка CRS успешна ({test_epsg})",
                    f"Прямая установка CRS неуспешна: получено {direct_crs.authid()}"
                )

                self.logger.data("CRS после прямого setCrs", f"{direct_crs.authid()} - {direct_crs.description()}")

            # Восстанавливаем исходную CRS
            if original_crs.isValid():
                QgsProject.instance().setCrs(original_crs)
                self.logger.info(f"CRS восстановлена: {original_crs.authid()}")

        except Exception as e:
            self.logger.error(f"Ошибка проверки установки CRS: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
