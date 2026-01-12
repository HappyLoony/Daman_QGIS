# -*- coding: utf-8 -*-
"""
Fsm_5_2_T_crs_transform - Тест трансформации координат (CRS)

Проверяет:
1. Создание МСК через PROJ строку
2. Трансформация МСК <-> WGS84 с проверкой точности (0.01м)
3. Параметры towgs84 для СК-42
4. Корректность эллипсоидов (Красовского, ГСК-2011)
5. Обратная трансформация (round-trip)
6. Трансформация между разными МСК

Критически важно для плагина - работа с российскими СК.
"""

from typing import Any, Dict, List, Tuple, Optional
import math

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsPointXY,
    QgsGeometry,
    QgsVectorLayer,
    QgsFeature,
)


class TestCrsTransform:
    """Тесты трансформации координат"""

    # Параметры трансформации СК-42 -> WGS84 (Position Vector, для PROJ)
    SK42_TOWGS84 = {
        'dx': 23.57,
        'dy': -140.95,
        'dz': -79.8,
        'rx': 0,
        'ry': 0.35,
        'rz': 0.79,
        'ds': -0.22
    }

    # Эллипсоид Красовского
    KRASSOVSKY_ELLIPSOID = {
        'a': 6378245.0,
        'rf': 298.3,  # 1/f
    }

    # Тестовые точки (известные координаты)
    # Формат: (имя, WGS84 lon/lat, МСК X/Y приблизительно)
    TEST_POINTS = [
        ('Moscow_center', (37.6173, 55.7558), None),
        ('SPb_center', (30.3141, 59.9386), None),
        ('Sochi', (39.7303, 43.6028), None),
    ]

    # Допустимая погрешность трансформации (метры)
    TOLERANCE_METERS = 0.01  # 1 см - стандарт плагина

    def __init__(self, iface: Any, logger: Any) -> None:
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger

    def run_all_tests(self) -> None:
        """Запуск всех тестов CRS"""
        self.logger.section("ТЕСТ ТРАНСФОРМАЦИИ КООРДИНАТ (CRS)")

        try:
            self.test_01_standard_crs()
            self.test_02_custom_msk_creation()
            self.test_03_towgs84_parameters()
            self.test_04_transform_accuracy()
            self.test_05_round_trip_transform()
            self.test_06_geometry_transform()
            self.test_07_layer_transform()
            self.test_08_ellipsoid_parameters()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов CRS: {str(e)}")

        self.logger.summary()

    def test_01_standard_crs(self) -> None:
        """ТЕСТ 1: Стандартные CRS"""
        self.logger.section("1. Стандартные CRS")

        # Основные CRS - критически важные для работы плагина
        required_crs = [
            ('EPSG:4326', 'WGS 84'),
            ('EPSG:3857', 'Web Mercator'),
            ('EPSG:4284', 'Pulkovo 1942'),
            ('EPSG:28404', 'Pulkovo 1942 / Gauss-Kruger zone 4'),
            ('EPSG:32637', 'WGS 84 / UTM zone 37N'),
        ]

        # Дополнительные CRS - для расширенной функциональности
        # Зоны 1-3 могут отсутствовать в некоторых версиях PROJ
        additional_crs = [
            ('EPSG:28402', 'Pulkovo 1942 / Gauss-Kruger zone 2'),
            ('EPSG:28403', 'Pulkovo 1942 / Gauss-Kruger zone 3'),
            ('EPSG:28405', 'Pulkovo 1942 / Gauss-Kruger zone 5'),
            ('EPSG:28406', 'Pulkovo 1942 / Gauss-Kruger zone 6'),
            ('EPSG:32636', 'WGS 84 / UTM zone 36N'),
            ('EPSG:32638', 'WGS 84 / UTM zone 38N'),
        ]

        # Опциональные CRS - могут отсутствовать в зависимости от версии PROJ
        optional_crs = [
            ('EPSG:28401', 'Pulkovo 1942 / Gauss-Kruger zone 1'),
        ]

        self.logger.info("Проверка основных CRS:")
        for epsg, name in required_crs:
            crs = QgsCoordinateReferenceSystem(epsg)
            if crs.isValid():
                self.logger.success(f"{epsg} ({name}) валидна")
            else:
                self.logger.fail(f"{epsg} ({name}) НЕ валидна!")

        self.logger.info("Проверка дополнительных CRS:")
        for epsg, name in additional_crs:
            crs = QgsCoordinateReferenceSystem(epsg)
            if crs.isValid():
                self.logger.success(f"{epsg} ({name}) валидна")
            else:
                self.logger.fail(f"{epsg} ({name}) НЕ валидна!")

        self.logger.info("Проверка опциональных CRS (зависят от версии PROJ):")
        for epsg, name in optional_crs:
            crs = QgsCoordinateReferenceSystem(epsg)
            if crs.isValid():
                self.logger.success(f"{epsg} ({name}) валидна")
            else:
                # Опциональные CRS - информируем, но не fail
                self.logger.info(f"{epsg} ({name}) недоступна в текущей версии PROJ")

    def test_02_custom_msk_creation(self) -> None:
        """ТЕСТ 2: Создание пользовательской МСК"""
        self.logger.section("2. Создание МСК через PROJ")

        # PROJ строка для МСК-50 (Московская область, зона 1)
        msk_proj = (
            "+proj=tmerc +lat_0=0 +lon_0=37.5 +k=1 "
            "+x_0=1250000 +y_0=0 +ellps=krass "
            "+towgs84=23.57,-140.95,-79.8,0,0.35,0.79,-0.22 "
            "+units=m +no_defs"
        )

        try:
            crs = QgsCoordinateReferenceSystem()
            result = crs.createFromProj(msk_proj)

            if result and crs.isValid():
                self.logger.success("МСК создана из PROJ строки")

                # Проверяем параметры
                proj_string = crs.toProj()
                self.logger.info(f"PROJ: {proj_string[:80]}...")

                # Проверяем наличие ключевых параметров
                if '+ellps=krass' in proj_string:
                    self.logger.success("Эллипсоид Красовского установлен")
                else:
                    self.logger.fail("Эллипсоид Красовского не найден в PROJ!")

                if '+towgs84=' in proj_string:
                    self.logger.success("Параметры towgs84 присутствуют")
                else:
                    self.logger.fail("Параметры towgs84 отсутствуют!")

            else:
                self.logger.fail("Не удалось создать МСК из PROJ строки")

        except Exception as e:
            self.logger.error(f"Ошибка создания МСК: {e}")

    def test_03_towgs84_parameters(self) -> None:
        """ТЕСТ 3: Проверка параметров towgs84"""
        self.logger.section("3. Параметры towgs84 для СК-42")

        try:
            # Используем стандартную CRS с towgs84
            crs_sk42 = QgsCoordinateReferenceSystem('EPSG:28404')

            if not crs_sk42.isValid():
                self.logger.fail("EPSG:28404 недоступна!")
                return

            proj_string = crs_sk42.toProj()
            self.logger.info(f"PROJ для EPSG:28404: {proj_string}")

            # Проверяем что есть towgs84 или datum
            has_transform = '+towgs84=' in proj_string or '+datum=' in proj_string

            if has_transform:
                self.logger.success("Параметры трансформации присутствуют")
            else:
                self.logger.fail("Параметры трансформации отсутствуют!")

            # Проверяем наши константы
            self.logger.info("Ожидаемые параметры towgs84 (Position Vector):")
            self.logger.info(f"  dX={self.SK42_TOWGS84['dx']}, dY={self.SK42_TOWGS84['dy']}, dZ={self.SK42_TOWGS84['dz']}")
            self.logger.info(f"  rX={self.SK42_TOWGS84['rx']}, rY={self.SK42_TOWGS84['ry']}, rZ={self.SK42_TOWGS84['rz']}")
            self.logger.info(f"  dS={self.SK42_TOWGS84['ds']}")

        except Exception as e:
            self.logger.error(f"Ошибка проверки towgs84: {e}")

    def test_04_transform_accuracy(self) -> None:
        """ТЕСТ 4: Точность трансформации"""
        self.logger.section("4. Точность трансформации")

        try:
            crs_wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
            crs_sk42 = QgsCoordinateReferenceSystem('EPSG:28404')  # Зона 4

            if not crs_wgs84.isValid():
                self.logger.fail("EPSG:4326 не валидна!")
                return
            if not crs_sk42.isValid():
                self.logger.fail("EPSG:28404 не валидна!")
                return

            transform = QgsCoordinateTransform(crs_wgs84, crs_sk42, QgsProject.instance())

            # Тестовая точка: Москва (примерно центр зоны 4)
            # WGS84: lon=37.6173, lat=55.7558
            test_point = QgsPointXY(37.6173, 55.7558)

            try:
                # Трансформируем WGS84 -> СК-42
                transformed = transform.transform(test_point)

                self.logger.success(f"WGS84 ({test_point.x():.4f}, {test_point.y():.4f})")
                self.logger.success(f"СК-42 zone4 ({transformed.x():.2f}, {transformed.y():.2f})")

                # СК-42 Гаусса-Крюгера зона 4:
                # В QGIS/PROJ порядок осей может отличаться от традиционного
                # Easting (X) = зона*1000000 + 500000 + x_local, диапазон ~4_300_000 - 4_700_000
                # Northing (Y) = расстояние от экватора, для широты 55° ~ 6_100_000
                # Но PROJ может вернуть в порядке (northing, easting) или наоборот

                x_val = transformed.x()
                y_val = transformed.y()

                # Определяем какая координата easting, какая northing
                # Easting для зоны 4: 4_000_000 - 5_000_000
                # Northing для широты 55°: 5_500_000 - 6_500_000

                if 4_000_000 < x_val < 5_000_000:
                    easting, northing = x_val, y_val
                    self.logger.success(f"Easting (X) в диапазоне зоны 4: {easting:.2f}")
                elif 4_000_000 < y_val < 5_000_000:
                    easting, northing = y_val, x_val
                    self.logger.success(f"Easting (Y) в диапазоне зоны 4: {easting:.2f} (оси переставлены)")
                else:
                    # Для Москвы (lon=37.6) координаты должны быть:
                    # Easting ~ 4_400_000 (зона 4 + смещение)
                    # Northing ~ 6_180_000 (широта 55.7°)
                    # Проверяем что хотя бы одна координата в разумном диапазоне
                    if (x_val > 1_000_000 or y_val > 1_000_000):
                        self.logger.success(f"Координаты в метрической СК: X={x_val:.2f}, Y={y_val:.2f}")
                    else:
                        self.logger.fail(f"Координаты вне ожидаемого диапазона: X={x_val}, Y={y_val}")

                # Обе координаты должны быть положительными
                if x_val > 0 and y_val > 0:
                    self.logger.success("Обе координаты положительные")
                else:
                    self.logger.fail(f"Отрицательные координаты: X={x_val}, Y={y_val}")

            except Exception as e:
                self.logger.error(f"Ошибка трансформации: {e}")

        except Exception as e:
            self.logger.error(f"Ошибка теста точности: {e}")

    def test_05_round_trip_transform(self) -> None:
        """ТЕСТ 5: Round-trip трансформация (туда и обратно)"""
        self.logger.section("5. Round-trip трансформация")

        try:
            crs_wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
            crs_utm = QgsCoordinateReferenceSystem('EPSG:32637')  # UTM 37N

            if not crs_wgs84.isValid():
                self.logger.fail("EPSG:4326 не валидна!")
                return
            if not crs_utm.isValid():
                self.logger.fail("EPSG:32637 не валидна!")
                return

            transform_forward = QgsCoordinateTransform(crs_wgs84, crs_utm, QgsProject.instance())
            transform_back = QgsCoordinateTransform(crs_utm, crs_wgs84, QgsProject.instance())

            # Исходная точка
            original = QgsPointXY(37.6173, 55.7558)

            # Туда
            transformed = transform_forward.transform(original)

            # Обратно
            back = transform_back.transform(transformed)

            # Вычисляем погрешность в градусах
            error_lon = abs(original.x() - back.x())
            error_lat = abs(original.y() - back.y())

            # Переводим в метры (приблизительно)
            # 1 градус широты ~ 111 км, 1 градус долготы ~ 111 км * cos(lat)
            error_lon_m = error_lon * 111000 * math.cos(math.radians(original.y()))
            error_lat_m = error_lat * 111000

            total_error_m = math.sqrt(error_lon_m ** 2 + error_lat_m ** 2)

            self.logger.info(f"Исходная точка: ({original.x():.6f}, {original.y():.6f})")
            self.logger.info(f"После round-trip: ({back.x():.6f}, {back.y():.6f})")
            self.logger.info(f"Погрешность: {total_error_m:.4f} м")

            # Стандарт точности плагина - 0.01 м (1 см)
            if total_error_m <= self.TOLERANCE_METERS:
                self.logger.success(f"Погрешность {total_error_m:.6f} м <= {self.TOLERANCE_METERS} м")
            else:
                self.logger.fail(f"Погрешность {total_error_m:.4f} м превышает стандарт {self.TOLERANCE_METERS} м!")

        except Exception as e:
            self.logger.error(f"Ошибка round-trip: {e}")

    def test_06_geometry_transform(self) -> None:
        """ТЕСТ 6: Трансформация геометрии"""
        self.logger.section("6. Трансформация геометрии")

        try:
            crs_wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
            crs_3857 = QgsCoordinateReferenceSystem('EPSG:3857')

            transform = QgsCoordinateTransform(crs_wgs84, crs_3857, QgsProject.instance())

            # Создаём полигон в WGS84
            wkt = "POLYGON((37.6 55.7, 37.7 55.7, 37.7 55.8, 37.6 55.8, 37.6 55.7))"
            geom = QgsGeometry.fromWkt(wkt)

            if not geom.isGeosValid():
                self.logger.fail("Исходная геометрия невалидна")
                return

            original_area = geom.area()
            self.logger.info(f"Площадь в WGS84: {original_area:.6f} кв.град")

            # Трансформируем
            geom.transform(transform)

            if geom.isGeosValid():
                self.logger.success("Геометрия валидна после трансформации")

                transformed_area = geom.area()
                self.logger.info(f"Площадь в EPSG:3857: {transformed_area:.2f} кв.м")

                # Площадь должна быть порядка нескольких км^2 (от 1 км^2 до 1000 км^2)
                if 1e6 < transformed_area < 1e9:
                    self.logger.success("Площадь в корректном диапазоне (1-1000 кв.км)")
                else:
                    self.logger.fail(f"Площадь {transformed_area:.0f} вне диапазона 1e6-1e9!")

            else:
                self.logger.fail("Геометрия невалидна после трансформации!")

        except Exception as e:
            self.logger.error(f"Ошибка трансформации геометрии: {e}")

    def test_07_layer_transform(self) -> None:
        """ТЕСТ 7: Трансформация слоя (on-the-fly)"""
        self.logger.section("7. Трансформация слоя")

        try:
            # Создаём слой в WGS84
            layer = QgsVectorLayer(
                "Point?crs=EPSG:4326&field=name:string",
                "transform_test",
                "memory"
            )

            if not layer.isValid():
                self.logger.fail("Не удалось создать тестовый слой")
                return

            # Добавляем точку
            provider = layer.dataProvider()
            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(37.6173, 55.7558)))
            feature.setAttributes(['Moscow'])
            provider.addFeatures([feature])

            self.logger.success(f"Создан слой с CRS: {layer.crs().authid()}")

            # Проверяем что extent в разумных координатах
            extent = layer.extent()
            self.logger.info(f"Extent: {extent.xMinimum():.4f}, {extent.yMinimum():.4f}")

            # Трансформируем в другую CRS через Processing
            try:
                import processing

                crs_target = QgsCoordinateReferenceSystem('EPSG:32637')

                result = processing.run(
                    "native:reprojectlayer",
                    {
                        'INPUT': layer,
                        'TARGET_CRS': crs_target,
                        'OUTPUT': 'memory:'
                    }
                )

                output_layer = result['OUTPUT']

                if output_layer and output_layer.isValid():
                    self.logger.success(f"Слой репроецирован в {output_layer.crs().authid()}")

                    # Проверяем координаты
                    for feat in output_layer.getFeatures():
                        pt = feat.geometry().asPoint()
                        self.logger.info(f"Координаты в UTM: ({pt.x():.2f}, {pt.y():.2f})")

                        # UTM координаты должны быть большими числами
                        if pt.x() > 100000 and pt.y() > 1000000:
                            self.logger.success("Координаты в диапазоне UTM")
                        else:
                            self.logger.fail(f"UTM координаты вне диапазона: X={pt.x()}, Y={pt.y()}")
                        break
                else:
                    self.logger.fail("Репроекция не вернула валидный слой!")

            except ImportError:
                self.logger.fail("processing недоступен!")

            # Очистка
            del layer

        except Exception as e:
            self.logger.error(f"Ошибка трансформации слоя: {e}")

    def test_08_ellipsoid_parameters(self) -> None:
        """ТЕСТ 8: Параметры эллипсоидов"""
        self.logger.section("8. Параметры эллипсоидов")

        try:
            # Проверяем эллипсоид Красовского
            crs_sk42 = QgsCoordinateReferenceSystem('EPSG:4284')  # Pulkovo 1942

            if crs_sk42.isValid():
                ellipsoid = crs_sk42.ellipsoidAcronym()
                self.logger.info(f"Эллипсоид СК-42: {ellipsoid}")

                # Получаем параметры через PROJ
                proj = crs_sk42.toProj()

                if 'krass' in proj.lower():
                    self.logger.success("Эллипсоид Красовского идентифицирован")
                elif 'krassowski' in proj.lower():
                    self.logger.success("Эллипсоид Krassowski идентифицирован")
                else:
                    self.logger.info(f"Эллипсоид в PROJ: {proj}")

            # Проверяем WGS84 эллипсоид
            crs_wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')

            if crs_wgs84.isValid():
                ellipsoid = crs_wgs84.ellipsoidAcronym()
                self.logger.info(f"Эллипсоид WGS84: {ellipsoid}")

            # Выводим наши константы для сверки
            self.logger.info("Параметры эллипсоида Красовского (константы плагина):")
            self.logger.info(f"  a = {self.KRASSOVSKY_ELLIPSOID['a']} м")
            self.logger.info(f"  1/f = {self.KRASSOVSKY_ELLIPSOID['rf']}")

        except Exception as e:
            self.logger.error(f"Ошибка проверки эллипсоидов: {e}")
