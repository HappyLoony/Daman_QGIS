# -*- coding: utf-8 -*-
"""
Fsm_5_2_T_processing - Тест Processing framework

Проверяет:
1. Доступность processing алгоритмов
2. Корректность выполнения базовых операций
3. Обработку ошибок в processing
4. Алгоритмы, используемые плагином (fixgeometries, dissolve, buffer)

Основано на best practices:
- pytest-qgis qgis_processing fixture
- QGIS Processing documentation
"""

from typing import Any, Dict, Optional
import tempfile
import os

from qgis.core import (
    QgsApplication, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsProcessingFeedback, QgsProcessingContext,
    QgsCoordinateReferenceSystem
)


class TestProcessing:
    """Тесты Processing framework"""

    def __init__(self, iface: Any, logger: Any) -> None:
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.context: Optional[QgsProcessingContext] = None
        self.feedback: Optional[QgsProcessingFeedback] = None

    def run_all_tests(self) -> None:
        """Запуск всех тестов Processing"""
        self.logger.section("ТЕСТ PROCESSING FRAMEWORK")

        try:
            self._setup_processing()
            self.test_01_processing_import()
            self.test_02_algorithm_registry()
            self.test_03_buffer_algorithm()
            self.test_04_fix_geometries()
            self.test_05_dissolve()
            self.test_06_error_handling()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов Processing: {str(e)}")

        self.logger.summary()

    def _setup_processing(self) -> None:
        """Инициализация Processing context и feedback"""
        try:
            self.context = QgsProcessingContext()
            self.feedback = QgsProcessingFeedback()

            # Устанавливаем проект
            from qgis.core import QgsProject
            self.context.setProject(QgsProject.instance())

        except Exception as e:
            self.logger.warning(f"Ошибка инициализации Processing context: {e}")

    def _create_test_layer(self, name: str = "test_layer") -> QgsVectorLayer:
        """Создать тестовый слой с полигонами"""
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326&field=id:integer&field=name:string",
            name,
            "memory"
        )

        provider = layer.dataProvider()

        # Добавляем несколько полигонов
        features = []
        for i in range(3):
            feature = QgsFeature()
            offset = i * 2
            wkt = f"POLYGON(({offset} 0, {offset + 1} 0, {offset + 1} 1, {offset} 1, {offset} 0))"
            feature.setGeometry(QgsGeometry.fromWkt(wkt))
            feature.setAttributes([i + 1, f"polygon_{i + 1}"])
            features.append(feature)

        provider.addFeatures(features)
        return layer

    def _create_invalid_geometry_layer(self) -> QgsVectorLayer:
        """Создать слой с невалидными геометриями"""
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326&field=id:integer",
            "invalid_geometries",
            "memory"
        )

        provider = layer.dataProvider()

        # Добавляем самопересекающийся полигон (bowtie)
        invalid_wkt = "POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))"
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromWkt(invalid_wkt))
        feature.setAttributes([1])
        provider.addFeatures([feature])

        return layer

    def test_01_processing_import(self) -> None:
        """ТЕСТ 1: Импорт processing"""
        self.logger.section("1. Импорт processing")

        try:
            import processing
            self.logger.success("import processing успешен")

            # Проверяем processing.run
            if hasattr(processing, 'run'):
                self.logger.success("processing.run доступен")
            else:
                self.logger.fail("processing.run недоступен!")

            # Проверяем processing.algorithmHelp
            if hasattr(processing, 'algorithmHelp'):
                self.logger.success("processing.algorithmHelp доступен")

        except ImportError as e:
            self.logger.error(f"Ошибка импорта processing: {e}")
        except Exception as e:
            self.logger.error(f"Неожиданная ошибка: {e}")

    def test_02_algorithm_registry(self) -> None:
        """ТЕСТ 2: Реестр алгоритмов"""
        self.logger.section("2. Реестр алгоритмов")

        try:
            registry = QgsApplication.processingRegistry()

            # Алгоритмы, которые использует плагин
            required_algorithms = [
                'native:fixgeometries',
                'native:dissolve',
                'native:buffer',
                'native:intersection',
                'native:difference',
                'native:clip',
                'native:extractbyattribute',
                'native:reprojectlayer',
            ]

            for alg_id in required_algorithms:
                alg = registry.algorithmById(alg_id)
                if alg:
                    self.logger.success(f"'{alg_id}' доступен")
                else:
                    self.logger.warning(f"'{alg_id}' недоступен")

        except Exception as e:
            self.logger.error(f"Ошибка проверки реестра: {e}")

    def test_03_buffer_algorithm(self) -> None:
        """ТЕСТ 3: Алгоритм buffer"""
        self.logger.section("3. native:buffer")

        try:
            import processing

            # Создаём тестовый слой
            layer = self._create_test_layer("buffer_test")

            if not layer.isValid():
                self.logger.fail("Тестовый слой не валиден")
                return

            # Выполняем buffer
            result = processing.run(
                "native:buffer",
                {
                    'INPUT': layer,
                    'DISTANCE': 0.1,
                    'SEGMENTS': 5,
                    'END_CAP_STYLE': 0,
                    'JOIN_STYLE': 0,
                    'MITER_LIMIT': 2,
                    'DISSOLVE': False,
                    'OUTPUT': 'memory:'
                },
                context=self.context,
                feedback=self.feedback
            )

            output_layer = result['OUTPUT']

            if isinstance(output_layer, QgsVectorLayer) and output_layer.isValid():
                self.logger.success("Buffer выполнен успешно")

                # Проверяем что площадь увеличилась
                original_area = sum(f.geometry().area() for f in layer.getFeatures())
                buffered_area = sum(f.geometry().area() for f in output_layer.getFeatures())

                if buffered_area > original_area:
                    self.logger.success(f"Площадь увеличилась: {original_area:.4f} -> {buffered_area:.4f}")
                else:
                    self.logger.fail("Площадь не увеличилась после buffer!")
            else:
                self.logger.fail("Результат buffer не валиден")

        except Exception as e:
            self.logger.error(f"Ошибка buffer: {e}")

    def test_04_fix_geometries(self) -> None:
        """ТЕСТ 4: Алгоритм fixgeometries"""
        self.logger.section("4. native:fixgeometries")

        try:
            import processing

            # Создаём слой с невалидными геометриями
            layer = self._create_invalid_geometry_layer()

            if not layer.isValid():
                self.logger.fail("Тестовый слой не валиден")
                return

            # Проверяем что геометрия невалидна
            for feature in layer.getFeatures():
                geom = feature.geometry()
                if not geom.isGeosValid():
                    self.logger.info("Найдена невалидная геометрия (как ожидалось)")
                    break

            # Выполняем fixgeometries
            result = processing.run(
                "native:fixgeometries",
                {
                    'INPUT': layer,
                    'OUTPUT': 'memory:'
                },
                context=self.context,
                feedback=self.feedback
            )

            output_layer = result['OUTPUT']

            if isinstance(output_layer, QgsVectorLayer) and output_layer.isValid():
                self.logger.success("fixgeometries выполнен")

                # Проверяем что все геометрии валидны
                all_valid = True
                for feature in output_layer.getFeatures():
                    if not feature.geometry().isGeosValid():
                        all_valid = False
                        break

                if all_valid:
                    self.logger.success("Все геометрии после fix валидны")
                else:
                    self.logger.warning("Не все геометрии исправлены")
            else:
                self.logger.fail("Результат fixgeometries не валиден")

        except Exception as e:
            self.logger.error(f"Ошибка fixgeometries: {e}")

    def test_05_dissolve(self) -> None:
        """ТЕСТ 5: Алгоритм dissolve"""
        self.logger.section("5. native:dissolve")

        try:
            import processing

            # Создаём слой с перекрывающимися полигонами
            layer = QgsVectorLayer(
                "Polygon?crs=EPSG:4326&field=category:string",
                "dissolve_test",
                "memory"
            )

            provider = layer.dataProvider()
            features = []

            # Два перекрывающихся полигона одной категории
            for i in range(2):
                feature = QgsFeature()
                offset = i * 0.5  # Перекрытие 50%
                wkt = f"POLYGON(({offset} 0, {offset + 1} 0, {offset + 1} 1, {offset} 1, {offset} 0))"
                feature.setGeometry(QgsGeometry.fromWkt(wkt))
                feature.setAttributes(["A"])
                features.append(feature)

            provider.addFeatures(features)

            initial_count = layer.featureCount()
            self.logger.info(f"Начальных объектов: {initial_count}")

            # Выполняем dissolve
            result = processing.run(
                "native:dissolve",
                {
                    'INPUT': layer,
                    'FIELD': ['category'],
                    'OUTPUT': 'memory:'
                },
                context=self.context,
                feedback=self.feedback
            )

            output_layer = result['OUTPUT']

            if isinstance(output_layer, QgsVectorLayer) and output_layer.isValid():
                final_count = output_layer.featureCount()
                self.logger.success(f"dissolve выполнен: {initial_count} -> {final_count} объектов")

                if final_count < initial_count:
                    self.logger.success("Объекты объединены корректно")
                else:
                    self.logger.warning("Количество объектов не уменьшилось")
            else:
                self.logger.fail("Результат dissolve не валиден")

        except Exception as e:
            self.logger.error(f"Ошибка dissolve: {e}")

    def test_06_error_handling(self) -> None:
        """ТЕСТ 6: Обработка ошибок"""
        self.logger.section("6. Обработка ошибок")

        try:
            import processing
            from qgis.core import QgsProcessingFeedback

            # Создаём "тихий" feedback для тестов ошибок (не выводит CRITICAL в лог)
            silent_feedback = QgsProcessingFeedback()

            # Тест 1: Несуществующий алгоритм
            try:
                processing.run(
                    "native:nonexistent_algorithm",
                    {'INPUT': 'memory:'},
                    context=self.context,
                    feedback=silent_feedback
                )
                self.logger.fail("Несуществующий алгоритм не вызвал ошибку!")
            except Exception:
                self.logger.success("Несуществующий алгоритм корректно вызывает исключение")

            # Тест 2: Невалидные параметры
            try:
                processing.run(
                    "native:buffer",
                    {
                        'INPUT': None,  # Невалидный input
                        'DISTANCE': "not_a_number",  # Невалидное значение
                        'OUTPUT': 'memory:'
                    },
                    context=self.context,
                    feedback=silent_feedback
                )
                self.logger.warning("Невалидные параметры не вызвали ошибку")
            except Exception:
                self.logger.success("Невалидные параметры корректно вызывают исключение")

        except Exception as e:
            self.logger.error(f"Ошибка теста error handling: {e}")
