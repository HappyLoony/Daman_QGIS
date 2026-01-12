# -*- coding: utf-8 -*-
"""
Fsm_5_2_T_performance - Тест производительности

Проверяет:
1. Время создания слоёв с большим количеством объектов
2. Время итерации по features
3. Время геометрических операций (buffer, dissolve)
4. Время записи/чтения атрибутов
5. Время трансформации координат
6. Benchmark сравнение разных подходов

Полезно для выявления узких мест и регрессий.
"""

from typing import Any, Dict, List, Tuple, Callable
import time
import gc

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsProject, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsApplication
)


class Timer:
    """Контекстный менеджер для замера времени"""

    def __init__(self, name: str = ""):
        self.name = name
        self.start_time = 0.0
        self.end_time = 0.0
        self.duration = 0.0

    def __enter__(self):
        gc.collect()  # Очистка мусора перед замером
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.end_time = time.perf_counter()
        self.duration = self.end_time - self.start_time

    @property
    def ms(self) -> float:
        """Время в миллисекундах"""
        return self.duration * 1000


class TestPerformance:
    """Тесты производительности"""

    # Пороговые значения (миллисекунды)
    THRESHOLDS = {
        'layer_creation_1000': 500,     # 1000 объектов за 500мс
        'layer_creation_10000': 5000,   # 10000 объектов за 5с
        'iteration_1000': 100,          # итерация 1000 объектов за 100мс
        'iteration_10000': 1000,        # итерация 10000 объектов за 1с
        'buffer_100': 500,              # buffer 100 объектов за 500мс
        'transform_1000': 200,          # трансформация 1000 точек за 200мс
        'attribute_read_1000': 100,     # чтение атрибутов 1000 объектов за 100мс
    }

    def __init__(self, iface: Any, logger: Any) -> None:
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.results: Dict[str, float] = {}

    def run_all_tests(self) -> None:
        """Запуск всех тестов производительности"""
        self.logger.section("ТЕСТ ПРОИЗВОДИТЕЛЬНОСТИ")

        try:
            self.test_01_layer_creation()
            self.test_02_feature_iteration()
            self.test_03_geometry_operations()
            self.test_04_attribute_operations()
            self.test_05_coordinate_transform()
            self.test_06_processing_benchmark()
            self.test_07_summary()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов performance: {str(e)}")

        self.logger.summary()

    def _create_test_layer(self, feature_count: int, name: str = "perf_test") -> QgsVectorLayer:
        """Создать тестовый слой с указанным количеством объектов"""
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326&field=id:integer&field=name:string&field=value:double",
            name,
            "memory"
        )

        provider = layer.dataProvider()
        features = []

        for i in range(feature_count):
            feat = QgsFeature()
            x = (i % 100) * 0.1
            y = (i // 100) * 0.1
            wkt = f"POLYGON(({x} {y}, {x + 0.09} {y}, {x + 0.09} {y + 0.09}, {x} {y + 0.09}, {x} {y}))"
            feat.setGeometry(QgsGeometry.fromWkt(wkt))
            feat.setAttributes([i, f'feature_{i}', float(i) * 1.5])
            features.append(feat)

        provider.addFeatures(features)
        return layer

    def test_01_layer_creation(self) -> None:
        """ТЕСТ 1: Создание слоёв"""
        self.logger.section("1. Создание слоёв")

        test_sizes = [100, 1000, 5000]

        for size in test_sizes:
            with Timer(f"create_{size}") as t:
                layer = self._create_test_layer(size, f"perf_layer_{size}")

            self.results[f'layer_creation_{size}'] = t.ms

            # Проверяем результат
            if layer.featureCount() == size:
                self.logger.info(f"{size} объектов: {t.ms:.1f} мс ({size / t.duration:.0f} obj/sec)")
            else:
                self.logger.fail(f"Создано {layer.featureCount()} вместо {size}!")

            # Проверяем порог
            threshold_key = f'layer_creation_{size}'
            if threshold_key in self.THRESHOLDS:
                if t.ms <= self.THRESHOLDS[threshold_key]:
                    self.logger.success(f"В пределах порога ({self.THRESHOLDS[threshold_key]} мс)")
                else:
                    self.logger.fail(f"Превышен порог! {t.ms:.1f} > {self.THRESHOLDS[threshold_key]} мс")

            del layer

    def test_02_feature_iteration(self) -> None:
        """ТЕСТ 2: Итерация по features"""
        self.logger.section("2. Итерация по features")

        test_sizes = [1000, 5000, 10000]

        for size in test_sizes:
            layer = self._create_test_layer(size, f"iter_layer_{size}")

            # Простая итерация
            with Timer(f"iterate_{size}") as t:
                count = 0
                for feat in layer.getFeatures():
                    count += 1

            self.results[f'iteration_{size}'] = t.ms
            self.logger.info(f"Итерация {size}: {t.ms:.1f} мс ({size / t.duration:.0f} feat/sec)")

            # Итерация с доступом к геометрии
            with Timer(f"iterate_geom_{size}") as t:
                total_area = 0.0
                for feat in layer.getFeatures():
                    total_area += feat.geometry().area()

            self.results[f'iteration_geom_{size}'] = t.ms
            self.logger.info(f"Итерация + area {size}: {t.ms:.1f} мс")

            # Итерация с доступом к атрибутам
            with Timer(f"iterate_attr_{size}") as t:
                names = []
                for feat in layer.getFeatures():
                    names.append(feat['name'])

            self.results[f'iteration_attr_{size}'] = t.ms
            self.logger.info(f"Итерация + attr {size}: {t.ms:.1f} мс")

            del layer

    def test_03_geometry_operations(self) -> None:
        """ТЕСТ 3: Геометрические операции"""
        self.logger.section("3. Геометрические операции")

        try:
            import processing

            layer = self._create_test_layer(500, "geom_ops_layer")

            # Buffer
            with Timer("buffer_500") as t:
                result = processing.run(
                    "native:buffer",
                    {
                        'INPUT': layer,
                        'DISTANCE': 0.01,
                        'SEGMENTS': 5,
                        'OUTPUT': 'memory:'
                    }
                )

            self.results['buffer_500'] = t.ms
            output = result.get('OUTPUT')
            if output and output.isValid():
                self.logger.success(f"Buffer 500 объектов: {t.ms:.1f} мс")
            else:
                self.logger.fail("Buffer не вернул валидный результат!")

            # Dissolve
            with Timer("dissolve_500") as t:
                result = processing.run(
                    "native:dissolve",
                    {
                        'INPUT': layer,
                        'OUTPUT': 'memory:'
                    }
                )

            self.results['dissolve_500'] = t.ms
            self.logger.success(f"Dissolve 500 объектов: {t.ms:.1f} мс")

            # FixGeometries
            with Timer("fixgeom_500") as t:
                result = processing.run(
                    "native:fixgeometries",
                    {
                        'INPUT': layer,
                        'OUTPUT': 'memory:'
                    }
                )

            self.results['fixgeom_500'] = t.ms
            self.logger.success(f"FixGeometries 500 объектов: {t.ms:.1f} мс")

            del layer

        except ImportError:
            self.logger.fail("processing недоступен!")

    def test_04_attribute_operations(self) -> None:
        """ТЕСТ 4: Операции с атрибутами"""
        self.logger.section("4. Операции с атрибутами")

        layer = self._create_test_layer(1000, "attr_ops_layer")

        # Чтение атрибутов
        with Timer("attr_read_1000") as t:
            values = []
            for feat in layer.getFeatures():
                values.append((feat['id'], feat['name'], feat['value']))

        self.results['attr_read_1000'] = t.ms
        self.logger.success(f"Чтение атрибутов 1000: {t.ms:.1f} мс")

        # Запись атрибутов (в режиме редактирования)
        layer.startEditing()

        with Timer("attr_write_1000") as t:
            for feat in layer.getFeatures():
                layer.changeAttributeValue(feat.id(), 2, feat['value'] * 2)  # Меняем value

        self.results['attr_write_1000'] = t.ms
        self.logger.success(f"Запись атрибутов 1000: {t.ms:.1f} мс")

        layer.rollBack()  # Откатываем изменения
        del layer

    def test_05_coordinate_transform(self) -> None:
        """ТЕСТ 5: Трансформация координат"""
        self.logger.section("5. Трансформация координат")

        crs_wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        crs_utm = QgsCoordinateReferenceSystem('EPSG:32637')

        transform = QgsCoordinateTransform(crs_wgs84, crs_utm, QgsProject.instance())

        # Трансформация отдельных точек
        point_count = 10000
        points = [QgsPointXY(37.0 + i * 0.0001, 55.0 + i * 0.0001) for i in range(point_count)]

        with Timer(f"transform_{point_count}") as t:
            transformed = []
            for pt in points:
                transformed.append(transform.transform(pt))

        self.results[f'transform_{point_count}'] = t.ms
        self.logger.info(f"Трансформация {point_count} точек: {t.ms:.1f} мс ({point_count / t.duration:.0f} pt/sec)")

        # Трансформация геометрии
        layer = self._create_test_layer(500, "transform_layer")

        with Timer("transform_geom_500") as t:
            for feat in layer.getFeatures():
                geom = feat.geometry()
                geom.transform(transform)

        self.results['transform_geom_500'] = t.ms
        self.logger.info(f"Трансформация 500 геометрий: {t.ms:.1f} мс")

        del layer

    def test_06_processing_benchmark(self) -> None:
        """ТЕСТ 6: Benchmark Processing алгоритмов"""
        self.logger.section("6. Processing benchmark")

        try:
            import processing

            # Создаём слой побольше
            layer = self._create_test_layer(1000, "benchmark_layer")

            algorithms = [
                ('native:buffer', {'DISTANCE': 0.01, 'SEGMENTS': 5}),
                ('native:centroids', {}),
                ('native:fixgeometries', {}),
            ]

            for alg_id, params in algorithms:
                try:
                    alg_params = {
                        'INPUT': layer,
                        'OUTPUT': 'memory:',
                        **params
                    }

                    with Timer(alg_id) as t:
                        result = processing.run(alg_id, alg_params)

                    self.results[alg_id] = t.ms

                    output = result.get('OUTPUT')
                    if output and output.isValid():
                        self.logger.info(f"{alg_id}: {t.ms:.1f} мс ({output.featureCount()} features)")
                    else:
                        self.logger.info(f"{alg_id}: {t.ms:.1f} мс")

                except Exception as e:
                    self.logger.fail(f"{alg_id}: ошибка - {e}")

            del layer

        except ImportError:
            self.logger.fail("processing недоступен!")

    def test_07_summary(self) -> None:
        """ТЕСТ 7: Сводка результатов"""
        self.logger.section("7. Сводка производительности")

        if not self.results:
            self.logger.fail("Нет результатов для сводки!")
            return

        # Выводим все результаты
        self.logger.info("Результаты (мс):")

        sorted_results = sorted(self.results.items(), key=lambda x: x[1], reverse=True)

        for name, duration in sorted_results:
            # Проверяем порог
            status = ""
            if name in self.THRESHOLDS:
                if duration <= self.THRESHOLDS[name]:
                    status = " [OK]"
                else:
                    status = f" [FAIL: {duration:.1f} > {self.THRESHOLDS[name]}]"

            self.logger.info(f"  {name}: {duration:.1f} мс{status}")

        # Статистика
        total_time = sum(self.results.values())
        self.logger.info(f"Общее время тестов: {total_time:.1f} мс ({total_time / 1000:.2f} сек)")

        # Рекомендации по узким местам
        slowest = sorted_results[:3]
        if slowest:
            self.logger.info("Самые медленные операции:")
            for name, duration in slowest:
                self.logger.info(f"  - {name}: {duration:.1f} мс")

        # Общая оценка - строгая проверка порогов
        threshold_violations = 0
        for name, duration in self.results.items():
            if name in self.THRESHOLDS and duration > self.THRESHOLDS[name]:
                threshold_violations += 1

        if threshold_violations == 0:
            self.logger.success("Все тесты в пределах пороговых значений")
        else:
            self.logger.fail(f"Превышено порогов: {threshold_violations}!")
