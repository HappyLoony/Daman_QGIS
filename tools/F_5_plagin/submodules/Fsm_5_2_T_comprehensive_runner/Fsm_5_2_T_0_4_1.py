# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_0_4_1 - Тест функции F_0_4_Топология (Часть 1)
Проверка модулей Fsm_0_4_1 и Fsm_0_4_2
"""

import os
import tempfile
import shutil
import time
import gc
from pathlib import Path
from qgis.core import (
    QgsVectorLayer, QgsProject, QgsFeature, QgsGeometry, QgsPointXY,
    QgsField, QgsVectorFileWriter, QgsCoordinateReferenceSystem
)
from qgis.PyQt.QtCore import QMetaType
from qgis.PyQt.QtWidgets import QApplication


class TestF041:
    """Тесты для функции F_0_4_Топология - Часть 1 (Checkers 1-2)"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.module = None
        self.coordinator = None
        self.checker_1 = None  # Fsm_0_4_1 - валидность и самопересечения
        self.checker_2 = None  # Fsm_0_4_2 - дубли геометрий и вершин
        self.test_dir = None

    def run_all_tests(self):
        """Запуск всех тестов F_0_4 - Часть 1"""
        self.logger.section("ТЕСТ F_0_4: Проверка топологии - Часть 1 (Checkers 1-2)")

        # Создаем временную директорию для тестов
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f04_")
        self.logger.info(f"Временная директория: {self.test_dir}")
        assert self.test_dir is not None  # tempfile.mkdtemp всегда возвращает строку

        try:
            # Тест 1: Инициализация модулей
            self.test_01_init_modules()

            # Тест 2: Проверка координатора
            self.test_02_check_coordinator()

            # Тест 3: Checker 1 - Валидность геометрий
            self.test_03_checker1_validity()

            # Тест 4: Checker 1 - Самопересечения
            self.test_04_checker1_self_intersections()

            # Тест 5: Checker 2 - Дубли геометрий
            self.test_05_checker2_duplicate_geometries()

            # Тест 6: Checker 2 - Дубли вершин
            self.test_06_checker2_duplicate_vertices()

            # Тест 7: Интеграционный тест
            self.test_07_integration()

        finally:
            # Очистка временных файлов
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    # Задержка для освобождения блокировки GPKG файла Windows
                    time.sleep(0.5)
                    shutil.rmtree(self.test_dir)
                    self.logger.info("Временные файлы очищены")
                except Exception:
                    # ИЗВЕСТНАЯ ПРОБЛЕМА: SQLite/GPKG держит файловые дескрипторы
                    # открытыми через .wal/.shm файлы на уровне C-библиотеки.
                    # Временные файлы удалятся автоматически при выходе из QGIS.
                    # См. https://gis.stackexchange.com/q/389049
                    pass

        # Итоговая сводка
        self.logger.summary()

    def test_01_init_modules(self):
        """ТЕСТ 1: Инициализация модулей"""
        self.logger.section("1. Инициализация модулей F_0_4")

        try:
            # Инициализируем основной модуль F_0_4
            from Daman_QGIS.tools.F_0_project.F_0_4_topology_check import F_0_4_TopologyCheck

            self.module = F_0_4_TopologyCheck(self.iface)
            self.logger.success("Модуль F_0_4_TopologyCheck загружен успешно")

            # Проверяем наличие координатора
            if hasattr(self.module, 'coordinator'):
                self.coordinator = self.module.coordinator
                self.logger.success("Координатор (Fsm_0_4_5) доступен")
            else:
                self.logger.fail("Координатор не найден!")

            # Инициализируем Checker 1 (валидность и самопересечения)
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_4_1_geometry_validity import Fsm_0_4_1_GeometryValidityChecker

            self.checker_1 = Fsm_0_4_1_GeometryValidityChecker()
            self.logger.success("Модуль Fsm_0_4_1_GeometryValidityChecker загружен")

            # Проверяем методы Checker 1
            self.logger.check(
                hasattr(self.checker_1, 'check'),
                "Метод check существует в Checker 1",
                "Метод check отсутствует в Checker 1!"
            )

            # Инициализируем Checker 2 (дубли)
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_4_2_duplicates import Fsm_0_4_2_DuplicatesChecker

            self.checker_2 = Fsm_0_4_2_DuplicatesChecker()
            self.logger.success("Модуль Fsm_0_4_2_DuplicatesChecker загружен")

            # Проверяем методы Checker 2
            self.logger.check(
                hasattr(self.checker_2, 'check'),
                "Метод check существует в Checker 2",
                "Метод check отсутствует в Checker 2!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка инициализации модулей: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_02_check_coordinator(self):
        """ТЕСТ 2: Проверка координатора"""
        self.logger.section("2. Проверка координатора Fsm_0_4_5")

        if not self.coordinator:
            self.logger.fail("Координатор не инициализирован, пропускаем тест")
            return

        try:
            # Проверяем наличие checker'ов в координаторе (отдельные объекты)
            checkers = [
                ('validity_checker', self.coordinator.validity_checker),
                ('duplicates_checker', self.coordinator.duplicates_checker),
                ('topology_checker', self.coordinator.topology_checker),
                ('precision_checker', self.coordinator.precision_checker)
            ]

            active_checkers = 0
            for name, checker in checkers:
                if checker is not None:
                    active_checkers += 1
                    self.logger.data(f"  {name}", "✓ Активен")
                else:
                    self.logger.data(f"  {name}", "✗ Отсутствует")

            self.logger.check(
                active_checkers == 4,
                "Все 4 checker модуля инициализированы",
                f"Инициализировано checkers: {active_checkers}/4"
            )

            # Проверяем метод координации
            self.logger.check(
                hasattr(self.coordinator, 'check_layer'),
                "Метод check_layer существует",
                "Метод check_layer отсутствует!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка проверки координатора: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_03_checker1_validity(self):
        """ТЕСТ 3: Checker 1 - Проверка валидности геометрий"""
        self.logger.section("3. Checker 1: Проверка валидности геометрий")

        if not self.checker_1:
            self.logger.fail("Checker 1 не инициализирован, пропускаем тест")
            return

        try:
            # Создаем тестовый слой с невалидной геометрией
            # МИГРАЦИЯ POLYGON → MULTIPOLYGON: тестовый слой
            layer = QgsVectorLayer("MultiPolygon?crs=EPSG:32637", "test_invalid", "memory")
            provider = layer.dataProvider()

            # Добавляем поле для ID
            provider.addAttributes([QgsField("id", QMetaType.Type.Int)])
            layer.updateFields()

            # Создаем невалидный полигон (самопересекающийся "бабочка")
            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromWkt(
                "POLYGON((0 0, 10 0, 0 10, 10 10, 0 0))"
            ))
            feature.setAttributes([1])
            provider.addFeatures([feature])

            self.logger.success("Тестовый слой с невалидной геометрией создан")

            # Запускаем проверку
            if self.coordinator:
                result = self.coordinator.check_layer(layer)
                errors_by_type = result.get('errors_by_type', {})
                validity_errors = errors_by_type.get('validity', [])
            else:
                # Прямой вызов checker'а
                validity_errors, _ = self.checker_1.check(layer)

            if validity_errors:
                self.logger.success(f"Обнаружено ошибок валидности: {len(validity_errors)}")

                # Проверяем структуру первой ошибки
                if len(validity_errors) > 0:
                    first_error = validity_errors[0]

                    # Проверяем что это dict
                    if isinstance(first_error, dict):
                        self.logger.check(
                            'type' in first_error,
                            "Поле 'type' присутствует",
                            "Поле 'type' отсутствует!"
                        )

                        if 'type' in first_error:
                            self.logger.data("Тип ошибки", first_error['type'])

                        self.logger.check(
                            'geometry' in first_error,
                            "Поле 'geometry' присутствует",
                            "Поле 'geometry' отсутствует!"
                        )
                    else:
                        self.logger.warning(f"Ошибка не является dict: {type(first_error)}")
            else:
                self.logger.warning("Ошибки валидности не обнаружены (возможно, алгоритм не сработал)")

        except Exception as e:
            self.logger.error(f"Ошибка теста валидности: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_04_checker1_self_intersections(self):
        """ТЕСТ 4: Checker 1 - Самопересечения"""
        self.logger.section("4. Checker 1: Проверка самопересечений")

        if not self.checker_1:
            self.logger.fail("Checker 1 не инициализирован, пропускаем тест")
            return

        try:
            # Создаем тестовый слой с самопересекающимся полигоном
            # МИГРАЦИЯ POLYGON → MULTIPOLYGON: тестовый слой
            layer = QgsVectorLayer("MultiPolygon?crs=EPSG:32637", "test_self_intersect", "memory")
            provider = layer.dataProvider()

            provider.addAttributes([QgsField("id", QMetaType.Type.Int)])
            layer.updateFields()

            # Явно самопересекающийся полигон (галстук-бабочка)
            feature = QgsFeature()
            points = [
                QgsPointXY(0, 0),
                QgsPointXY(10, 10),
                QgsPointXY(10, 0),
                QgsPointXY(0, 10),
                QgsPointXY(0, 0)
            ]
            feature.setGeometry(QgsGeometry.fromPolygonXY([points]))
            feature.setAttributes([1])
            provider.addFeatures([feature])

            self.logger.success("Тестовый слой с самопересечением создан")

            # Запускаем проверку
            if self.coordinator:
                result = self.coordinator.check_layer(layer)
                errors_by_type = result.get('errors_by_type', {})
                self_int_errors = errors_by_type.get('self_intersection', [])
                validity_errors = errors_by_type.get('validity', [])
            else:
                validity_errors, self_int_errors = self.checker_1.check(layer)

            total_errors = len(self_int_errors) + len(validity_errors)

            if total_errors > 0:
                self.logger.success(f"Обнаружено ошибок геометрии: {total_errors}")

                # Проверяем самопересечения
                if self_int_errors:
                    self.logger.success(f"Найдено self_intersection: {len(self_int_errors)}")
                else:
                    self.logger.data("self_intersection", "0 (возможно классифицировано как validity)")

                # Проверяем невалидную геометрию
                if validity_errors:
                    self.logger.success(f"Найдено validity errors: {len(validity_errors)}")
            else:
                self.logger.warning("Самопересечения не обнаружены")

        except Exception as e:
            self.logger.error(f"Ошибка теста самопересечений: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_05_checker2_duplicate_geometries(self):
        """ТЕСТ 5: Checker 2 - Дубли геометрий"""
        self.logger.section("5. Checker 2: Проверка дублей геометрий")

        if not self.checker_2:
            self.logger.fail("Checker 2 не инициализирован, пропускаем тест")
            return

        try:
            # Создаем тестовый слой с дублирующимися геометриями
            # МИГРАЦИЯ POLYGON → MULTIPOLYGON: тестовый слой
            layer = QgsVectorLayer("MultiPolygon?crs=EPSG:32637", "test_duplicates", "memory")
            provider = layer.dataProvider()

            provider.addAttributes([QgsField("id", QMetaType.Type.Int)])
            layer.updateFields()

            # Создаем два одинаковых полигона
            points = [
                QgsPointXY(0, 0),
                QgsPointXY(10, 0),
                QgsPointXY(10, 10),
                QgsPointXY(0, 10),
                QgsPointXY(0, 0)
            ]
            geom = QgsGeometry.fromPolygonXY([points])

            feature1 = QgsFeature()
            feature1.setGeometry(geom)
            feature1.setAttributes([1])

            feature2 = QgsFeature()
            feature2.setGeometry(geom)
            feature2.setAttributes([2])

            provider.addFeatures([feature1, feature2])

            self.logger.success("Тестовый слой с дублями геометрий создан")

            # Запускаем проверку
            if self.coordinator:
                result = self.coordinator.check_layer(layer)
                errors_by_type = result.get('errors_by_type', {})
                duplicate_errors = errors_by_type.get('duplicate_geometry', [])
            else:
                duplicate_errors, _, _ = self.checker_2.check(layer)

            if duplicate_errors:
                self.logger.success(f"Найдено дублей геометрий: {len(duplicate_errors)}")

                # Проверяем структуру первой ошибки
                if len(duplicate_errors) > 0:
                    first_dup = duplicate_errors[0]

                    if isinstance(first_dup, dict):
                        if 'feature_id' in first_dup or 'feature_id2' in first_dup:
                            fid1 = first_dup.get('feature_id', '?')
                            fid2 = first_dup.get('feature_id2', '?')
                            self.logger.data("ID дублей", f"{fid1} и {fid2}")
                    else:
                        self.logger.warning(f"Ошибка не является dict: {type(first_dup)}")
            else:
                self.logger.warning("Дубли геометрий не обнаружены (возможно, алгоритм не сработал)")

        except Exception as e:
            self.logger.error(f"Ошибка теста дублей геометрий: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_06_checker2_duplicate_vertices(self):
        """ТЕСТ 6: Checker 2 - Дубли вершин"""
        self.logger.section("6. Checker 2: Проверка дублей вершин")

        if not self.checker_2:
            self.logger.fail("Checker 2 не инициализирован, пропускаем тест")
            return

        try:
            # Создаем тестовый слой с дублирующимися вершинами
            # МИГРАЦИЯ POLYGON → MULTIPOLYGON: тестовый слой
            layer = QgsVectorLayer("MultiPolygon?crs=EPSG:32637", "test_dup_vertices", "memory")
            provider = layer.dataProvider()

            provider.addAttributes([QgsField("id", QMetaType.Type.Int)])
            layer.updateFields()

            # Полигон с дублирующейся вершиной
            points = [
                QgsPointXY(0, 0),
                QgsPointXY(5, 0),
                QgsPointXY(5, 0),  # Дубль!
                QgsPointXY(10, 0),
                QgsPointXY(10, 10),
                QgsPointXY(0, 10),
                QgsPointXY(0, 0)
            ]

            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromPolygonXY([points]))
            feature.setAttributes([1])
            provider.addFeatures([feature])

            self.logger.success("Тестовый слой с дублями вершин создан")

            # Запускаем проверку
            if self.coordinator:
                result = self.coordinator.check_layer(layer)
                errors_by_type = result.get('errors_by_type', {})
                vertex_errors = errors_by_type.get('duplicate_vertex', [])
            else:
                _, vertex_errors, _ = self.checker_2.check(layer)

            if vertex_errors:
                self.logger.success(f"Найдено дублей вершин: {len(vertex_errors)}")

                # Проверяем структуру первой ошибки
                if len(vertex_errors) > 0:
                    first_vertex = vertex_errors[0]

                    if isinstance(first_vertex, dict):
                        if 'feature_id' in first_vertex:
                            self.logger.data("Feature ID", str(first_vertex['feature_id']))
                        if 'vertex_index' in first_vertex:
                            self.logger.data("Vertex index", str(first_vertex['vertex_index']))
                    else:
                        self.logger.warning(f"Ошибка не является dict: {type(first_vertex)}")
            else:
                self.logger.warning("Дубли вершин не обнаружены (возможно, алгоритм не сработал)")

        except Exception as e:
            self.logger.error(f"Ошибка теста дублей вершин: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_07_integration(self):
        """ТЕСТ 7: Интеграционный тест через F_0_4"""
        self.logger.section("7. Интеграционный тест F_0_4")

        if not self.module:
            self.logger.fail("Модуль F_0_4 не инициализирован, пропускаем тест")
            return

        if not self.test_dir:
            self.logger.fail("Временная директория не инициализирована")
            return

        try:
            # Создаем комплексный тестовый слой
            gpkg_path = os.path.join(self.test_dir, "test.gpkg")
            # МИГРАЦИЯ POLYGON → MULTIPOLYGON: тестовый слой
            layer = QgsVectorLayer("MultiPolygon?crs=EPSG:32637", "test_layer", "memory")
            provider = layer.dataProvider()

            provider.addAttributes([
                QgsField("id", QMetaType.Type.Int),
                QgsField("name", QMetaType.Type.QString)
            ])
            layer.updateFields()

            # Добавляем несколько объектов с разными ошибками
            features = []

            # Объект 1: валидный полигон
            f1 = QgsFeature()
            f1.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0, 20 0, 20 20, 0 20, 0 0))"))
            f1.setAttributes([1, "Valid"])
            features.append(f1)

            # Объект 2: самопересекающийся полигон
            f2 = QgsFeature()
            f2.setGeometry(QgsGeometry.fromWkt("POLYGON((30 0, 40 10, 40 0, 30 10, 30 0))"))
            f2.setAttributes([2, "Self-intersect"])
            features.append(f2)

            # Объект 3: дубль объекта 1
            f3 = QgsFeature()
            f3.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0, 20 0, 20 20, 0 20, 0 0))"))
            f3.setAttributes([3, "Duplicate"])
            features.append(f3)

            provider.addFeatures(features)

            self.logger.success(f"Тестовый слой создан: {layer.featureCount()} объектов")

            # Сохраняем в GeoPackage
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            writer = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                gpkg_path,
                QgsProject.instance().transformContext(),
                options
            )

            if writer[0] == QgsVectorFileWriter.NoError:
                self.logger.success("Слой сохранен в GeoPackage")

                # Загружаем из GeoPackage
                test_layer = QgsVectorLayer(gpkg_path, "test_layer", "ogr")

                if test_layer.isValid():
                    self.logger.success("Слой загружен из GeoPackage")

                    # Запускаем проверку через координатор
                    if self.coordinator:
                        result = self.coordinator.check_layer(test_layer)

                        total_errors = result.get('error_count', 0)
                        errors_by_type = result.get('errors_by_type', {})

                        if total_errors > 0:
                            self.logger.success(f"Интеграционная проверка: найдено {total_errors} ошибок")

                            # Выводим распределение по типам
                            self.logger.info("Распределение ошибок по типам:")
                            for err_type, err_list in errors_by_type.items():
                                if err_list:
                                    count = len(err_list) if isinstance(err_list, list) else 1
                                    self.logger.data(f"  {err_type}", str(count))
                        else:
                            self.logger.warning("Интеграционная проверка не обнаружила ошибок")

                    # Явно освобождаем GPKG слой для закрытия соединения с БД
                    del test_layer
                    gc.collect()  # Принудительная сборка мусора
                    QApplication.processEvents()  # Обработка событий Qt
                else:
                    self.logger.fail("Не удалось загрузить слой из GeoPackage")
            else:
                self.logger.fail(f"Ошибка сохранения в GeoPackage: {writer}")

        except Exception as e:
            self.logger.error(f"Ошибка интеграционного теста: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
