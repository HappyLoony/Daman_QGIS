# -*- coding: utf-8 -*-
"""
Fsm_5_2_T_memory_leak - Тест утечек памяти и очистки ресурсов

Проверяет:
1. Корректное удаление слоёв (без segfault)
2. Очистка QgsProject
3. Циклическое создание/удаление слоёв
4. Отсутствие утечек при работе с геометриями

Основано на best practices:
- pytest-qgis: layer fixtures с автоочисткой
- clean_qgis_layer decorator
- Memory management в PyQGIS
"""

from typing import Any, List
import gc

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsCoordinateReferenceSystem, QgsMemoryProviderUtils
)


class TestMemoryLeak:
    """Тесты утечек памяти"""

    def __init__(self, iface: Any, logger: Any) -> None:
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger

    def run_all_tests(self) -> None:
        """Запуск всех тестов памяти"""
        self.logger.section("ТЕСТ УТЕЧЕК ПАМЯТИ")

        try:
            self.test_01_layer_cleanup()
            self.test_02_project_cleanup()
            self.test_03_cyclic_layer_creation()
            self.test_04_geometry_memory()
            self.test_05_feature_iteration()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов памяти: {str(e)}")

        self.logger.summary()

    def _get_memory_usage(self) -> int:
        """Получить текущее использование памяти (приблизительно)"""
        try:
            import tracemalloc
            if tracemalloc.is_tracing():
                current, peak = tracemalloc.get_traced_memory()
                return current
        except ImportError:
            pass

        # Fallback - количество объектов gc
        return len(gc.get_objects())

    def _create_test_layer(self, name: str, feature_count: int = 100) -> QgsVectorLayer:
        """Создать тестовый слой с указанным количеством объектов"""
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326&field=id:integer&field=data:string",
            name,
            "memory"
        )

        provider = layer.dataProvider()
        features = []

        for i in range(feature_count):
            feature = QgsFeature()
            x = i % 10
            y = i // 10
            wkt = f"POLYGON(({x} {y}, {x + 1} {y}, {x + 1} {y + 1}, {x} {y + 1}, {x} {y}))"
            feature.setGeometry(QgsGeometry.fromWkt(wkt))
            feature.setAttributes([i, f"data_{i}" * 10])  # Строка ~70 байт
            features.append(feature)

        provider.addFeatures(features)
        return layer

    def test_01_layer_cleanup(self) -> None:
        """ТЕСТ 1: Корректное удаление слоёв"""
        self.logger.section("1. Удаление слоёв")

        try:
            project = QgsProject.instance()
            initial_layers = len(project.mapLayers())

            # Создаём и добавляем слой
            layer = self._create_test_layer("cleanup_test", 50)
            layer_id = layer.id()

            project.addMapLayer(layer)

            if layer_id in project.mapLayers():
                self.logger.success("Слой добавлен в проект")
            else:
                self.logger.fail("Слой не добавлен!")
                return

            # Удаляем слой
            project.removeMapLayer(layer_id)

            if layer_id not in project.mapLayers():
                self.logger.success("Слой удалён из проекта")
            else:
                self.logger.fail("Слой не удалён!")

            # Форсируем сборку мусора
            gc.collect()

            # Проверяем что количество слоёв вернулось
            final_layers = len(project.mapLayers())
            if final_layers == initial_layers:
                self.logger.success("Количество слоёв восстановлено")
            else:
                self.logger.warning(f"Слоёв: было {initial_layers}, стало {final_layers}")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {e}")

    def test_02_project_cleanup(self) -> None:
        """ТЕСТ 2: Очистка проекта"""
        self.logger.section("2. Очистка проекта")

        try:
            project = QgsProject.instance()

            # Добавляем несколько слоёв
            layers = []
            for i in range(5):
                layer = self._create_test_layer(f"project_test_{i}", 20)
                project.addMapLayer(layer)
                layers.append(layer.id())

            self.logger.info(f"Добавлено слоёв: {len(layers)}")

            # Очищаем проект
            project.removeAllMapLayers()
            gc.collect()

            if len(project.mapLayers()) == 0:
                self.logger.success("Все слои удалены")
            else:
                self.logger.fail(f"Осталось слоёв: {len(project.mapLayers())}")

            # Проверяем layer tree
            root = project.layerTreeRoot()
            if len(root.children()) == 0:
                self.logger.success("Layer tree очищен")
            else:
                self.logger.warning(f"В layer tree осталось: {len(root.children())} узлов")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {e}")

    def test_03_cyclic_layer_creation(self) -> None:
        """ТЕСТ 3: Циклическое создание/удаление слоёв"""
        self.logger.section("3. Циклическое создание/удаление")

        try:
            project = QgsProject.instance()
            iterations = 10
            features_per_layer = 50

            # Начальное состояние
            gc.collect()
            initial_objects = len(gc.get_objects())

            for i in range(iterations):
                layer = self._create_test_layer(f"cyclic_{i}", features_per_layer)
                project.addMapLayer(layer)
                project.removeMapLayer(layer.id())

            gc.collect()
            final_objects = len(gc.get_objects())

            # Допускаем небольшой рост (кэши, внутренние структуры)
            object_diff = final_objects - initial_objects
            threshold = 1000  # Допустимый порог

            if object_diff < threshold:
                self.logger.success(f"Память стабильна (+{object_diff} объектов за {iterations} итераций)")
            else:
                self.logger.warning(f"Возможная утечка: +{object_diff} объектов за {iterations} итераций")

            self.logger.info(f"Объектов gc: {initial_objects} -> {final_objects}")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {e}")

    def test_04_geometry_memory(self) -> None:
        """ТЕСТ 4: Память при работе с геометриями"""
        self.logger.section("4. Память геометрий")

        try:
            iterations = 100

            gc.collect()
            initial_objects = len(gc.get_objects())

            # Создаём и сразу удаляем геометрии
            for i in range(iterations):
                geom = QgsGeometry.fromWkt(f"POLYGON(({i} 0, {i + 1} 0, {i + 1} 1, {i} 1, {i} 0))")

                # Операции с геометрией
                _ = geom.area()
                _ = geom.centroid()
                _ = geom.buffer(0.1, 5)

                del geom

            gc.collect()
            final_objects = len(gc.get_objects())

            object_diff = final_objects - initial_objects

            if object_diff < 500:
                self.logger.success(f"Геометрии очищаются корректно (+{object_diff})")
            else:
                self.logger.warning(f"Возможная утечка геометрий: +{object_diff}")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {e}")

    def test_05_feature_iteration(self) -> None:
        """ТЕСТ 5: Память при итерации по объектам"""
        self.logger.section("5. Итерация по объектам")

        try:
            # Создаём большой слой
            layer = self._create_test_layer("iteration_test", 1000)

            gc.collect()
            initial_objects = len(gc.get_objects())

            # Итерируем несколько раз
            for _ in range(5):
                total_area = 0
                for feature in layer.getFeatures():
                    geom = feature.geometry()
                    total_area += geom.area()

            gc.collect()
            final_objects = len(gc.get_objects())

            self.logger.info(f"Общая площадь: {total_area:.2f}")

            object_diff = final_objects - initial_objects

            if object_diff < 100:
                self.logger.success(f"Итерация не создаёт утечек (+{object_diff})")
            else:
                self.logger.warning(f"Возможная утечка при итерации: +{object_diff}")

            # Очистка
            del layer
            gc.collect()

        except Exception as e:
            self.logger.error(f"Ошибка теста: {e}")
