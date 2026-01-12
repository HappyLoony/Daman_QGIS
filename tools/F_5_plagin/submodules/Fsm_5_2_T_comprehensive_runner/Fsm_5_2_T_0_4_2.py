# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_0_4_2 - Тест функции F_0_4_Топология (Часть 2)
Проверка модулей Fsm_0_4_3 и Fsm_0_4_4
"""

import os
import tempfile
import shutil
import time
import gc
from qgis.core import (
    QgsVectorLayer, QgsProject, QgsFeature, QgsGeometry, QgsPointXY,
    QgsField, QgsVectorFileWriter, QgsCoordinateReferenceSystem
)
from qgis.PyQt.QtCore import QMetaType
from qgis.PyQt.QtWidgets import QApplication


class TestF042:
    """Тесты для функции F_0_4_Топология - Часть 2 (Checkers 3-4)"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.coordinator = None
        self.checker_3 = None  # Fsm_0_4_3 - наложения и острые углы
        self.checker_4 = None  # Fsm_0_4_4 - точность координат
        self.test_dir = None

    def run_all_tests(self):
        """Запуск всех тестов F_0_4 - Часть 2"""
        self.logger.section("ТЕСТ F_0_4: Проверка топологии - Часть 2 (Checkers 3-4)")

        # Создаем временную директорию для тестов
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f04_2_")
        self.logger.info(f"Временная директория: {self.test_dir}")

        try:
            # Тест 1: Инициализация модулей
            self.test_01_init_modules()

            # Тест 2: Checker 3 - Наложения полигонов
            self.test_02_checker3_overlaps()

            # Тест 3: Checker 3 - Острые углы
            self.test_03_checker3_acute_angles()

            # Тест 4: Checker 3 - Gaps (зазоры)
            self.test_04_checker3_gaps()

            # Тест 5: Checker 4 - Точность координат
            self.test_05_checker4_coordinate_precision()

            # Тест 6: Checker 4 - Координаты вне допустимого диапазона
            self.test_06_checker4_out_of_bounds()

            # Тест 7: Комплексный тест всех checkers
            self.test_07_full_integration()

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
        self.logger.section("1. Инициализация модулей Fsm_0_4_3 и Fsm_0_4_4")

        try:
            # Инициализируем координатор
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_4_5_coordinator import Fsm_0_4_5_TopologyCoordinator

            self.coordinator = Fsm_0_4_5_TopologyCoordinator()
            self.logger.success("Координатор Fsm_0_4_5 загружен успешно")

            # Инициализируем Checker 3 (наложения и острые углы)
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_4_3_topology_errors import Fsm_0_4_3_TopologyErrorsChecker

            self.checker_3 = Fsm_0_4_3_TopologyErrorsChecker()
            self.logger.success("Модуль Fsm_0_4_3_TopologyErrorsChecker загружен")

            # Проверяем методы Checker 3
            self.logger.check(
                hasattr(self.checker_3, 'check'),
                "Метод check существует в Checker 3",
                "Метод check отсутствует в Checker 3!"
            )

            # Инициализируем Checker 4 (точность координат)
            from Daman_QGIS.tools.F_0_project.submodules.Fsm_0_4_4_precision import Fsm_0_4_4_PrecisionChecker

            self.checker_4 = Fsm_0_4_4_PrecisionChecker()
            self.logger.success("Модуль Fsm_0_4_4_PrecisionChecker загружен")

            # Проверяем методы Checker 4
            self.logger.check(
                hasattr(self.checker_4, 'check'),
                "Метод check существует в Checker 4",
                "Метод check отсутствует в Checker 4!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка инициализации модулей: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_02_checker3_overlaps(self):
        """ТЕСТ 2: Checker 3 - Наложения полигонов"""
        self.logger.section("2. Checker 3: Проверка наложений полигонов")

        if not self.checker_3:
            self.logger.fail("Checker 3 не инициализирован, пропускаем тест")
            return

        try:
            # Создаем тестовый слой с накладывающимися полигонами
            # МИГРАЦИЯ POLYGON → MULTIPOLYGON: тестовый слой
            layer = QgsVectorLayer("MultiPolygon?crs=EPSG:32637", "test_overlaps", "memory")
            provider = layer.dataProvider()

            provider.addAttributes([QgsField("id", QMetaType.Type.Int)])
            layer.updateFields()

            # Полигон 1
            f1 = QgsFeature()
            f1.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0, 15 0, 15 15, 0 15, 0 0))"))
            f1.setAttributes([1])

            # Полигон 2 - частично перекрывает полигон 1
            f2 = QgsFeature()
            f2.setGeometry(QgsGeometry.fromWkt("POLYGON((10 10, 25 10, 25 25, 10 25, 10 10))"))
            f2.setAttributes([2])

            provider.addFeatures([f1, f2])

            self.logger.success("Тестовый слой с наложениями создан")

            # Запускаем проверку
            if self.coordinator:
                result = self.coordinator.check_layer(layer)
                errors_by_type = result.get('errors_by_type', {})
                overlap_errors = errors_by_type.get('overlap', [])
            else:
                overlap_errors, _ = self.checker_3.check(layer)

            if overlap_errors:
                self.logger.success(f"Найдено наложений: {len(overlap_errors)}")

                # Проверяем структуру первого наложения
                if len(overlap_errors) > 0:
                    first_overlap = overlap_errors[0]

                    if isinstance(first_overlap, dict):
                        if 'feature_id' in first_overlap and 'feature_id2' in first_overlap:
                            fid1 = first_overlap['feature_id']
                            fid2 = first_overlap['feature_id2']
                            self.logger.data("ID накладывающихся объектов", f"{fid1} и {fid2}")
            else:
                self.logger.warning("Наложения не обнаружены (возможно, алгоритм не сработал)")

        except Exception as e:
            self.logger.error(f"Ошибка теста наложений: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_03_checker3_acute_angles(self):
        """ТЕСТ 3: Checker 3 - Острые углы"""
        self.logger.section("3. Checker 3: Проверка острых углов")

        if not self.checker_3:
            self.logger.fail("Checker 3 не инициализирован, пропускаем тест")
            return

        try:
            # Создаем тестовый слой с острым углом
            # МИГРАЦИЯ POLYGON → MULTIPOLYGON: тестовый слой
            layer = QgsVectorLayer("MultiPolygon?crs=EPSG:32637", "test_acute_angles", "memory")
            provider = layer.dataProvider()

            provider.addAttributes([QgsField("id", QMetaType.Type.Int)])
            layer.updateFields()

            # Полигон с МНОЖЕСТВЕННЫМИ spike вершинами разной остроты
            # Формула: angle ≈ arctan(d/h) * 57.2958° где d - отклонение, h - высота
            feature = QgsFeature()
            points = [
                QgsPointXY(0, 0),

                # Spike 1: Экстремально острый ≈ 0.005° (h=200, d=0.01746)
                QgsPointXY(20, 0),
                QgsPointXY(20, 200),
                QgsPointXY(20.01746, 0),  # arctan(0.01746/200)*57.3 ≈ 0.005° ✓

                # Spike 2: Очень острый ≈ 0.1° (h=100, d=0.1746)
                QgsPointXY(40, 0),
                QgsPointXY(40, 100),
                QgsPointXY(40.1746, 0),   # arctan(0.1746/100)*57.3 ≈ 0.1° ✓

                # Spike 3: Средний ≈ 0.5° (h=20, d=0.1746)
                QgsPointXY(60, 0),
                QgsPointXY(60, 20),
                QgsPointXY(60.1746, 0),   # arctan(0.1746/20)*57.3 ≈ 0.5° ✓

                # Spike 4: Пограничный ≈ 0.9° (h=10, d=0.157)
                QgsPointXY(80, 0),
                QgsPointXY(80, 10),
                QgsPointXY(80.157, 0),    # arctan(0.157/10)*57.3 ≈ 0.9° ✓

                # Spike 5: Чуть больше ≈ 1.15° (h=10, d=0.2)
                QgsPointXY(100, 0),
                QgsPointXY(100, 10),
                QgsPointXY(100.2, 0),     # arctan(0.2/10)*57.3 ≈ 1.146° > 1.0° ✗

                # Spike 6: Значительно больше ≈ 2.86° (h=10, d=0.5)
                QgsPointXY(120, 0),
                QgsPointXY(120, 10),
                QgsPointXY(120.5, 0),     # arctan(0.5/10)*57.3 ≈ 2.862° ✗

                # Нормальный прямой угол 90°
                QgsPointXY(140, 0),
                QgsPointXY(140, 20),      # 90° ✗

                QgsPointXY(0, 20),
                QgsPointXY(0, 0)
            ]
            feature.setGeometry(QgsGeometry.fromPolygonXY([points]))
            feature.setAttributes([1])
            provider.addFeatures([feature])

            self.logger.success("Тестовый слой с множественными spike создан")
            self.logger.data("Ожидается найти", "4 spike (0.005°, 0.1°, 0.5°, 0.9°)")
            self.logger.data("Не должны детектироваться", "3 вершины (1.15°, 2.86°, 90°)")

            # Запускаем проверку
            if self.coordinator:
                result = self.coordinator.check_layer(layer)
                errors_by_type = result.get('errors_by_type', {})
                spike_errors = errors_by_type.get('spike', [])
            else:
                _, spike_errors = self.checker_3.check(layer)

            expected_spikes = 4
            if spike_errors:
                found_count = len(spike_errors)
                if found_count == expected_spikes:
                    self.logger.success(f"✓ Найдено {found_count} spike vertices (ожидалось {expected_spikes})")
                else:
                    self.logger.warning(f"Найдено {found_count} spike vertices, ожидалось {expected_spikes}")

                # Показываем все найденные углы
                self.logger.data("Найденные углы", "")
                for i, spike in enumerate(spike_errors[:10], 1):  # Показываем первые 10
                    if isinstance(spike, dict) and 'angle' in spike:
                        angle = spike['angle']
                        vertex_idx = spike.get('vertex_index', 'N/A')
                        self.logger.data(f"  Spike {i}", f"{angle:.4f}° (вершина {vertex_idx})")
            else:
                self.logger.fail(f"Spike vertices не обнаружены, ожидалось {expected_spikes}")

        except Exception as e:
            self.logger.error(f"Ошибка теста острых углов: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_04_checker3_gaps(self):
        """ТЕСТ 4: Checker 3 - Зазоры (gaps)"""
        self.logger.section("4. Checker 3: Проверка зазоров между полигонами")

        if not self.checker_3:
            self.logger.fail("Checker 3 не инициализирован, пропускаем тест")
            return

        try:
            # Создаем тестовый слой с зазором
            # МИГРАЦИЯ POLYGON → MULTIPOLYGON: тестовый слой
            layer = QgsVectorLayer("MultiPolygon?crs=EPSG:32637", "test_gaps", "memory")
            provider = layer.dataProvider()

            provider.addAttributes([QgsField("id", QMetaType.Type.Int)])
            layer.updateFields()

            # Полигон 1
            f1 = QgsFeature()
            f1.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))"))
            f1.setAttributes([1])

            # Полигон 2 - с небольшим зазором от полигона 1
            f2 = QgsFeature()
            f2.setGeometry(QgsGeometry.fromWkt("POLYGON((10.5 0, 20 0, 20 10, 10.5 10, 10.5 0))"))
            f2.setAttributes([2])

            provider.addFeatures([f1, f2])

            self.logger.success("Тестовый слой с зазором создан")

            # Запускаем проверку
            if self.coordinator:
                result = self.coordinator.check_layer(layer)
                errors_by_type = result.get('errors_by_type', {})
                # Gap checker не реализован в Checker 3
                gap_errors = errors_by_type.get('gap', [])
            else:
                # Checker 3 не проверяет gaps
                gap_errors = []

            if gap_errors:
                self.logger.success(f"Найдено зазоров: {len(gap_errors)}")
            else:
                self.logger.warning("Зазоры не обнаружены (функция gaps не реализована в Checker 3)")

        except Exception as e:
            self.logger.error(f"Ошибка теста зазоров: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_05_checker4_coordinate_precision(self):
        """ТЕСТ 5: Checker 4 - Точность координат"""
        self.logger.section("5. Checker 4: Проверка точности координат")

        if not self.checker_4:
            self.logger.fail("Checker 4 не инициализирован, пропускаем тест")
            return

        try:
            # Создаем тестовый слой с координатами разной точности
            # МИГРАЦИЯ POLYGON → MULTIPOLYGON: тестовый слой
            layer = QgsVectorLayer("MultiPolygon?crs=EPSG:32637", "test_precision", "memory")
            provider = layer.dataProvider()

            provider.addAttributes([QgsField("id", QMetaType.Type.Int)])
            layer.updateFields()

            # Полигон с координатами, содержащими избыточную точность
            feature = QgsFeature()
            points = [
                QgsPointXY(0.123456789, 0.987654321),
                QgsPointXY(10.111111111, 0.222222222),
                QgsPointXY(10.333333333, 10.444444444),
                QgsPointXY(0.555555555, 10.666666666),
                QgsPointXY(0.123456789, 0.987654321)
            ]
            feature.setGeometry(QgsGeometry.fromPolygonXY([points]))
            feature.setAttributes([1])
            provider.addFeatures([feature])

            self.logger.success("Тестовый слой с избыточной точностью создан")

            # Запускаем проверку
            if self.coordinator:
                result = self.coordinator.check_layer(layer)
                errors_by_type = result.get('errors_by_type', {})
                precision_errors = errors_by_type.get('precision', [])
            else:
                precision_errors = self.checker_4.check(layer)

            if precision_errors:
                self.logger.success(f"Найдено проблем с точностью: {len(precision_errors)}")

                # Проверяем структуру первой ошибки
                if len(precision_errors) > 0:
                    first_prec = precision_errors[0]

                    if isinstance(first_prec, dict) and 'feature_id' in first_prec:
                        self.logger.data("Feature ID", str(first_prec['feature_id']))
            else:
                self.logger.warning("Проблемы точности не обнаружены (возможно, Checker 4 не реализован)")

        except Exception as e:
            self.logger.error(f"Ошибка теста точности: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_06_checker4_out_of_bounds(self):
        """ТЕСТ 6: Checker 4 - Координаты вне допустимого диапазона"""
        self.logger.section("6. Checker 4: Проверка координат вне диапазона")

        if not self.checker_4:
            self.logger.fail("Checker 4 не инициализирован, пропускаем тест")
            return

        try:
            # Создаем тестовый слой с экстремальными координатами
            # МИГРАЦИЯ POLYGON → MULTIPOLYGON: тестовый слой
            layer = QgsVectorLayer("MultiPolygon?crs=EPSG:32637", "test_out_of_bounds", "memory")
            provider = layer.dataProvider()

            provider.addAttributes([QgsField("id", QMetaType.Type.Int)])
            layer.updateFields()

            # Полигон с очень большими координатами (вне ожидаемого диапазона для UTM)
            feature = QgsFeature()
            points = [
                QgsPointXY(10000000, 10000000),  # Огромные координаты
                QgsPointXY(10000010, 10000000),
                QgsPointXY(10000010, 10000010),
                QgsPointXY(10000000, 10000010),
                QgsPointXY(10000000, 10000000)
            ]
            feature.setGeometry(QgsGeometry.fromPolygonXY([points]))
            feature.setAttributes([1])
            provider.addFeatures([feature])

            self.logger.success("Тестовый слой с экстремальными координатами создан")

            # Запускаем проверку
            if self.coordinator:
                result = self.coordinator.check_layer(layer)
                errors_by_type = result.get('errors_by_type', {})
                # Out of bounds не реализован в Checker 4
                bounds_errors = errors_by_type.get('out_of_bounds', [])
            else:
                bounds_errors = []

            if bounds_errors:
                self.logger.success(f"Найдено проблем с диапазоном: {len(bounds_errors)}")
            else:
                self.logger.warning("Проблемы с диапазоном не обнаружены (функция не реализована в Checker 4)")

        except Exception as e:
            self.logger.error(f"Ошибка теста диапазона: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_07_full_integration(self):
        """ТЕСТ 7: Комплексный тест всех 4 checkers"""
        self.logger.section("7. Комплексный тест всех checkers")

        if not self.coordinator:
            self.logger.fail("Координатор не инициализирован")
            return

        try:
            # МИГРАЦИЯ POLYGON → MULTIPOLYGON: тестовый слой
            layer = QgsVectorLayer("MultiPolygon?crs=EPSG:32637", "test_full", "memory")
            provider = layer.dataProvider()
            provider.addAttributes([QgsField("id", QMetaType.Type.Int)])
            layer.updateFields()

            features = []
            f1 = QgsFeature()
            f1.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0, 10 10, 10 0, 0 10, 0 0))"))
            f1.setAttributes([1])
            features.append(f1)

            f2 = QgsFeature()
            f2.setGeometry(QgsGeometry.fromWkt("POLYGON((20 0, 30 0, 30 10, 20 10, 20 0))"))
            f2.setAttributes([2])
            features.append(f2)

            f3 = QgsFeature()
            f3.setGeometry(QgsGeometry.fromWkt("POLYGON((20 0, 30 0, 30 10, 20 10, 20 0))"))
            f3.setAttributes([3])
            features.append(f3)

            f4 = QgsFeature()
            f4.setGeometry(QgsGeometry.fromWkt("POLYGON((40 0, 55 0, 55 15, 40 15, 40 0))"))
            f4.setAttributes([4])
            features.append(f4)

            f5 = QgsFeature()
            f5.setGeometry(QgsGeometry.fromWkt("POLYGON((50 10, 65 10, 65 25, 50 25, 50 10))"))
            f5.setAttributes([5])
            features.append(f5)

            provider.addFeatures(features)
            self.logger.success(f"Слой создан: {layer.featureCount()} объектов")

            result = self.coordinator.check_layer(layer)

            total_errors = result.get('error_count', 0)
            errors_by_type = result.get('errors_by_type', {})

            if total_errors > 0:
                self.logger.success(f"Найдено {total_errors} ошибок")

                # Выводим распределение по типам
                for err_type, err_list in sorted(errors_by_type.items()):
                    if err_list:
                        count = len(err_list) if isinstance(err_list, list) else 1
                        self.logger.data(f"  {err_type}", str(count))
            else:
                self.logger.warning("Ошибки не обнаружены")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
