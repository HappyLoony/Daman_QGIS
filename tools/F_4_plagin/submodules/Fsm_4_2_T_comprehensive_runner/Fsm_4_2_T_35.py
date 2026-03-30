# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_35 - Тестирование M_35 ZprGpmtManager

Тестирует:
- Импорт модуля и существование класса
- Инициализацию конструктора
- is_zpr_layer() - определение слоёв ЗПР по префиксу
- _collect_and_unite_geometries() - объединение геометрий
- _create_points_memory_layer() - создание точечного слоя
- Точность координат 0.01м (snappedToGrid)
- Edge cases: пустые слои, единственный полигон
"""

from qgis.core import (
    QgsGeometry, QgsVectorLayer, QgsFeature, QgsFields, QgsField,
    QgsMemoryProviderUtils, Qgis, QgsPointXY, QgsCoordinateReferenceSystem
)
from qgis.PyQt.QtCore import QMetaType


class TestZprGpmtManager:
    """Тесты M_35 ZprGpmtManager"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.manager = None

    def run_all_tests(self):
        """Запуск всех тестов M_35"""
        self.logger.section("ТЕСТ M_35: ZprGpmtManager")

        try:
            self.test_01_import()
            self.test_02_constructor()
            self.test_03_class_attributes()
            self.test_04_public_methods()
            self.test_05_is_zpr_layer_positive()
            self.test_06_is_zpr_layer_negative()
            self.test_07_collect_unite_two_adjacent()
            self.test_08_collect_unite_empty_layers()
            self.test_09_collect_unite_single_polygon()
            self.test_10_collect_unite_overlapping()
            self.test_11_points_layer_creation()
            self.test_12_coordinate_precision()
            self.test_13_gpmt_layer_fields()
            self.test_14_area_calculation()
            self.test_15_multipolygon_conversion()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов M_35: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    # --- Вспомогательные методы ---

    def _create_test_crs(self):
        """CRS для тестовых слоёв (метрическая проекция)."""
        return QgsCoordinateReferenceSystem("EPSG:32637")

    def _create_polygon_layer(self, name, wkt_list, crs=None):
        """Создать тестовый полигональный слой из WKT строк."""
        if crs is None:
            crs = self._create_test_crs()

        fields = QgsFields()
        fields.append(QgsField("id", QMetaType.Type.Int))

        layer = QgsMemoryProviderUtils.createMemoryLayer(
            name, fields, Qgis.WkbType.MultiPolygon, crs
        )
        layer.startEditing()

        for i, wkt in enumerate(wkt_list):
            feat = QgsFeature(fields)
            geom = QgsGeometry.fromWkt(wkt)
            if geom and not geom.isEmpty():
                # Конвертируем в Multi если нужно
                if geom.isMultipart() is False:
                    geom.convertToMultiType()
                feat.setGeometry(geom)
            feat.setAttributes([i + 1])
            layer.addFeature(feat)

        layer.commitChanges()
        return layer

    def _create_empty_layer(self, name, crs=None):
        """Создать пустой полигональный слой."""
        if crs is None:
            crs = self._create_test_crs()
        fields = QgsFields()
        layer = QgsMemoryProviderUtils.createMemoryLayer(
            name, fields, Qgis.WkbType.MultiPolygon, crs
        )
        return layer

    # --- Тесты ---

    def test_01_import(self):
        """ТЕСТ 1: Импорт модуля и существование класса"""
        self.logger.section("1. Импорт ZprGpmtManager")
        try:
            from Daman_QGIS.managers.export.M_35_zpr_gpmt_manager import ZprGpmtManager
            self.logger.check(
                ZprGpmtManager is not None,
                "ZprGpmtManager импортирован",
                "ZprGpmtManager не найден"
            )
        except ImportError as e:
            self.logger.fail(f"Ошибка импорта: {e}")

    def test_02_constructor(self):
        """ТЕСТ 2: Инициализация конструктора"""
        self.logger.section("2. Конструктор ZprGpmtManager")
        try:
            from Daman_QGIS.managers.export.M_35_zpr_gpmt_manager import ZprGpmtManager
            self.manager = ZprGpmtManager(self.iface)

            self.logger.check(
                self.manager is not None,
                "Менеджер создан без layer_manager",
                "Менеджер не создан"
            )
            self.logger.check(
                self.manager.iface is self.iface,
                "iface сохранён корректно",
                "iface не соответствует переданному"
            )
            self.logger.check(
                self.manager.layer_manager is None,
                "layer_manager = None (опциональный)",
                "layer_manager должен быть None"
            )

            # С layer_manager
            mgr2 = ZprGpmtManager(self.iface, layer_manager="mock")
            self.logger.check(
                mgr2.layer_manager == "mock",
                "layer_manager передан корректно",
                "layer_manager не сохранён"
            )
        except Exception as e:
            self.logger.fail(f"Ошибка конструктора: {e}")

    def test_03_class_attributes(self):
        """ТЕСТ 3: Атрибуты класса (константы)"""
        self.logger.section("3. Атрибуты класса")
        if not self.manager:
            self.logger.fail("Менеджер не инициализирован (пропуск)")
            return

        self.logger.check(
            hasattr(self.manager, 'ZPR_PREFIXES'),
            "ZPR_PREFIXES определён",
            "ZPR_PREFIXES отсутствует"
        )
        self.logger.check(
            "L_1_12_" in self.manager.ZPR_PREFIXES,
            "L_1_12_ в ZPR_PREFIXES (площадные ЗПР)",
            "L_1_12_ не найден в ZPR_PREFIXES"
        )
        self.logger.check(
            "L_1_13_" in self.manager.ZPR_PREFIXES,
            "L_1_13_ в ZPR_PREFIXES (линейные ЗПР)",
            "L_1_13_ не найден в ZPR_PREFIXES"
        )
        self.logger.check(
            self.manager.GPMT_LAYER_NAME == "L_1_14_1_ГПМТ",
            f"GPMT_LAYER_NAME = '{self.manager.GPMT_LAYER_NAME}'",
            f"GPMT_LAYER_NAME неверен: '{self.manager.GPMT_LAYER_NAME}'"
        )
        self.logger.check(
            self.manager.GPMT_POINTS_LAYER_NAME == "L_1_14_3_Т_ГПМТ",
            f"GPMT_POINTS_LAYER_NAME = '{self.manager.GPMT_POINTS_LAYER_NAME}'",
            f"GPMT_POINTS_LAYER_NAME неверен: '{self.manager.GPMT_POINTS_LAYER_NAME}'"
        )

    def test_04_public_methods(self):
        """ТЕСТ 4: Наличие публичных методов"""
        self.logger.section("4. Публичные методы")
        if not self.manager:
            self.logger.fail("Менеджер не инициализирован (пропуск)")
            return

        methods = [
            'rebuild_gpmt', 'get_zpr_layers', 'get_gpmt_layer',
            'get_gpmt_points_layer', 'clear_gpmt', 'is_zpr_layer',
            '_collect_and_unite_geometries', '_create_gpmt_layer',
            '_create_gpmt_points_layer', '_create_points_memory_layer',
            '_save_to_gpkg', '_apply_style', '_apply_layer_visibility'
        ]
        for method in methods:
            self.logger.check(
                hasattr(self.manager, method),
                f"Метод {method}() существует",
                f"Метод {method}() отсутствует"
            )

    def test_05_is_zpr_layer_positive(self):
        """ТЕСТ 5: is_zpr_layer() - положительные случаи"""
        self.logger.section("5. is_zpr_layer() - положительные")
        if not self.manager:
            self.logger.fail("Менеджер не инициализирован (пропуск)")
            return

        positive_names = [
            "L_1_12_1_ОКС",
            "L_1_12_3_ВО",
            "L_1_13_2_СЕТИ_ПО",
            "L_1_12_99_Тест",
            "L_1_13_1_РЕК_АД",
        ]
        for name in positive_names:
            result = self.manager.is_zpr_layer(name)
            self.logger.check(
                result is True,
                f"'{name}' -> True",
                f"'{name}' -> {result}, ожидалось True"
            )

    def test_06_is_zpr_layer_negative(self):
        """ТЕСТ 6: is_zpr_layer() - отрицательные случаи"""
        self.logger.section("6. is_zpr_layer() - отрицательные")
        if not self.manager:
            self.logger.fail("Менеджер не инициализирован (пропуск)")
            return

        negative_names = [
            "L_1_14_1_ГПМТ",
            "L_1_1_1_Границы_работ",
            "L_1_11_1_Тест",
            "Произвольный_слой",
            "",
        ]
        for name in negative_names:
            result = self.manager.is_zpr_layer(name)
            self.logger.check(
                result is False,
                f"'{name}' -> False",
                f"'{name}' -> {result}, ожидалось False"
            )

    def test_07_collect_unite_two_adjacent(self):
        """ТЕСТ 7: Объединение двух смежных полигонов"""
        self.logger.section("7. _collect_and_unite_geometries() - два смежных полигона")
        if not self.manager:
            self.logger.fail("Менеджер не инициализирован (пропуск)")
            return

        try:
            # Два смежных квадрата: [0,0]-[10,10] и [10,0]-[20,10]
            layer1 = self._create_polygon_layer(
                "L_1_12_1_test",
                ["POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))"]
            )
            layer2 = self._create_polygon_layer(
                "L_1_12_2_test",
                ["POLYGON((10 0, 20 0, 20 10, 10 10, 10 0))"]
            )

            united, crs = self.manager._collect_and_unite_geometries([layer1, layer2])

            self.logger.check(
                united is not None and not united.isEmpty(),
                "Объединённая геометрия не пустая",
                "Объединённая геометрия пустая или None"
            )

            if united and not united.isEmpty():
                area = united.area()
                self.logger.check(
                    abs(area - 200.0) < 0.1,
                    f"Площадь = {area:.1f} (ожидалось 200.0)",
                    f"Площадь = {area:.1f}, ожидалось 200.0"
                )

                # Объединённый результат - один полигон (смежные)
                self.logger.check(
                    crs is not None,
                    "CRS определён",
                    "CRS = None"
                )

        except Exception as e:
            self.logger.fail(f"Ошибка объединения: {e}")

    def test_08_collect_unite_empty_layers(self):
        """ТЕСТ 8: Объединение пустых слоёв"""
        self.logger.section("8. _collect_and_unite_geometries() - пустые слои")
        if not self.manager:
            self.logger.fail("Менеджер не инициализирован (пропуск)")
            return

        try:
            empty_layer = self._create_empty_layer("L_1_12_empty")
            united, crs = self.manager._collect_and_unite_geometries([empty_layer])

            self.logger.check(
                united is None,
                "Пустой слой -> united = None",
                f"Пустой слой -> united не None (тип: {type(united).__name__})"
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_09_collect_unite_single_polygon(self):
        """ТЕСТ 9: Единственный полигон - passthrough"""
        self.logger.section("9. _collect_and_unite_geometries() - единственный полигон")
        if not self.manager:
            self.logger.fail("Менеджер не инициализирован (пропуск)")
            return

        try:
            layer = self._create_polygon_layer(
                "L_1_12_1_single",
                ["POLYGON((100 200, 200 200, 200 300, 100 300, 100 200))"]
            )

            united, crs = self.manager._collect_and_unite_geometries([layer])

            self.logger.check(
                united is not None and not united.isEmpty(),
                "Единственный полигон -> геометрия сохранена",
                "Единственный полигон -> геометрия потеряна"
            )

            if united and not united.isEmpty():
                area = united.area()
                self.logger.check(
                    abs(area - 10000.0) < 0.1,
                    f"Площадь = {area:.1f} (ожидалось 10000.0)",
                    f"Площадь = {area:.1f}, ожидалось 10000.0"
                )

        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_10_collect_unite_overlapping(self):
        """ТЕСТ 10: Перекрывающиеся полигоны - площадь учитывает перекрытие"""
        self.logger.section("10. _collect_and_unite_geometries() - перекрытие")
        if not self.manager:
            self.logger.fail("Менеджер не инициализирован (пропуск)")
            return

        try:
            # Два квадрата 10x10 с перекрытием 5x10 (общая площадь = 150, не 200)
            layer = self._create_polygon_layer(
                "L_1_12_1_overlap",
                [
                    "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))",
                    "POLYGON((5 0, 15 0, 15 10, 5 10, 5 0))"
                ]
            )

            united, crs = self.manager._collect_and_unite_geometries([layer])

            self.logger.check(
                united is not None and not united.isEmpty(),
                "Перекрывающиеся полигоны объединены",
                "Объединение перекрывающихся полигонов провалилось"
            )

            if united and not united.isEmpty():
                area = united.area()
                # unaryUnion устраняет перекрытие: 10*10 + 10*10 - 5*10 = 150
                self.logger.check(
                    abs(area - 150.0) < 0.1,
                    f"Площадь = {area:.1f} (перекрытие учтено, ожидалось 150.0)",
                    f"Площадь = {area:.1f}, ожидалось 150.0 (перекрытие не учтено?)"
                )

        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_11_points_layer_creation(self):
        """ТЕСТ 11: Создание точечного memory layer"""
        self.logger.section("11. _create_points_memory_layer() - базовый")
        if not self.manager:
            self.logger.fail("Менеджер не инициализирован (пропуск)")
            return

        try:
            crs = self._create_test_crs()

            # Имитируем данные от M_20
            points_data = [
                {
                    'point': QgsPointXY(500000.0, 6000000.0),
                    'id': 1,
                    'contour_point_index': 1,
                    'contour_type': 'Внешний',
                    'contour_number': 1,
                    'x_geodetic': 6000000.0,
                    'y_geodetic': 500000.0,
                },
                {
                    'point': QgsPointXY(500100.0, 6000000.0),
                    'id': 2,
                    'contour_point_index': 2,
                    'contour_type': 'Внешний',
                    'contour_number': 1,
                    'x_geodetic': 6000000.0,
                    'y_geodetic': 500100.0,
                },
                {
                    'point': QgsPointXY(500100.0, 6000100.0),
                    'id': 3,
                    'contour_point_index': 3,
                    'contour_type': 'Внешний',
                    'contour_number': 1,
                    'x_geodetic': 6000100.0,
                    'y_geodetic': 500100.0,
                },
            ]

            layer = self.manager._create_points_memory_layer(points_data, crs)

            self.logger.check(
                layer is not None,
                "Точечный слой создан",
                "Точечный слой = None"
            )

            if layer:
                self.logger.check(
                    layer.isValid(),
                    "Слой валиден",
                    "Слой невалиден"
                )
                self.logger.check(
                    layer.featureCount() == 3,
                    f"Количество точек: {layer.featureCount()} (ожидалось 3)",
                    f"Количество точек: {layer.featureCount()}, ожидалось 3"
                )

                # Проверяем поля
                field_names = [f.name() for f in layer.fields()]
                expected_fields = ["ID", "ID_Точки_контура", "Тип_контура",
                                   "Номер_контура", "X", "Y"]
                for fname in expected_fields:
                    self.logger.check(
                        fname in field_names,
                        f"Поле '{fname}' присутствует",
                        f"Поле '{fname}' отсутствует"
                    )

        except Exception as e:
            self.logger.fail(f"Ошибка создания точечного слоя: {e}")

    def test_12_coordinate_precision(self):
        """ТЕСТ 12: Точность координат 0.01м"""
        self.logger.section("12. Точность координат 0.01м")
        if not self.manager:
            self.logger.fail("Менеджер не инициализирован (пропуск)")
            return

        try:
            crs = self._create_test_crs()

            # Координаты с избыточной точностью
            points_data = [
                {
                    'point': QgsPointXY(500000.12345, 6000000.98765),
                    'id': 1,
                    'contour_point_index': 1,
                    'contour_type': 'Внешний',
                    'contour_number': 1,
                    'x_geodetic': 6000000.98765,
                    'y_geodetic': 500000.12345,
                },
            ]

            layer = self.manager._create_points_memory_layer(points_data, crs)

            if layer and layer.featureCount() > 0:
                feat = next(layer.getFeatures())
                geom = feat.geometry()
                point = geom.asPoint()

                # snappedToGrid(0.01, 0.01) должен округлить
                x_rounded = round(point.x(), 2)
                y_rounded = round(point.y(), 2)

                self.logger.check(
                    abs(point.x() - 500000.12) < 0.005,
                    f"X = {point.x():.4f} (ожидалось ~500000.12)",
                    f"X = {point.x():.4f}, точность нарушена"
                )
                self.logger.check(
                    abs(point.y() - 6000000.99) < 0.005,
                    f"Y = {point.y():.4f} (ожидалось ~6000000.99)",
                    f"Y = {point.y():.4f}, точность нарушена"
                )
            else:
                self.logger.fail("Слой пуст, невозможно проверить точность")

        except Exception as e:
            self.logger.fail(f"Ошибка проверки точности: {e}")

    def test_13_gpmt_layer_fields(self):
        """ТЕСТ 13: Структура полей слоя ГПМТ"""
        self.logger.section("13. _create_gpmt_layer() - структура полей")
        if not self.manager:
            self.logger.fail("Менеджер не инициализирован (пропуск)")
            return

        try:
            crs = self._create_test_crs()
            geom = QgsGeometry.fromWkt(
                "MULTIPOLYGON(((0 0, 100 0, 100 100, 0 100, 0 0)))"
            )

            layer = self.manager._create_gpmt_layer(geom, 10000, crs)

            self.logger.check(
                layer is not None,
                "ГПМТ слой создан",
                "ГПМТ слой = None"
            )

            if layer:
                self.logger.check(
                    layer.isValid(),
                    "Слой валиден",
                    "Слой невалиден"
                )
                self.logger.check(
                    layer.featureCount() == 1,
                    f"Объектов: {layer.featureCount()} (ожидалось 1)",
                    f"Объектов: {layer.featureCount()}, ожидалось 1"
                )

                field_names = [f.name() for f in layer.fields()]
                self.logger.check(
                    "area_sqm" in field_names,
                    "Поле 'area_sqm' присутствует",
                    "Поле 'area_sqm' отсутствует"
                )
                self.logger.check(
                    "area_ga" in field_names,
                    "Поле 'area_ga' присутствует",
                    "Поле 'area_ga' отсутствует"
                )

                # Проверяем атрибуты
                feat = next(layer.getFeatures())
                self.logger.check(
                    feat["area_sqm"] == 10000,
                    f"area_sqm = {feat['area_sqm']} (ожидалось 10000)",
                    f"area_sqm = {feat['area_sqm']}, ожидалось 10000"
                )
                self.logger.check(
                    feat["area_ga"] == "1,0000",
                    f"area_ga = '{feat['area_ga']}' (ожидалось '1,0000')",
                    f"area_ga = '{feat['area_ga']}', ожидалось '1,0000'"
                )

        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_14_area_calculation(self):
        """ТЕСТ 14: Вычисление площади через int(round())"""
        self.logger.section("14. Площадь ГПМТ - int(round())")
        if not self.manager:
            self.logger.fail("Менеджер не инициализирован (пропуск)")
            return

        try:
            # Квадрат 57x57 = 3249 кв.м
            geom = QgsGeometry.fromWkt(
                "POLYGON((0 0, 57 0, 57 57, 0 57, 0 0))"
            )
            area = int(round(geom.area()))
            self.logger.check(
                area == 3249,
                f"Площадь 57x57 = {area} кв.м (ожидалось 3249)",
                f"Площадь 57x57 = {area}, ожидалось 3249"
            )

            # Проверяем формат гектаров
            area_ga = area / 10000.0
            area_ga_str = f"{area_ga:.4f}".replace('.', ',')
            self.logger.check(
                area_ga_str == "0,3249",
                f"В гектарах: '{area_ga_str}' (ожидалось '0,3249')",
                f"В гектарах: '{area_ga_str}', ожидалось '0,3249'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_15_multipolygon_conversion(self):
        """ТЕСТ 15: Конвертация Polygon -> MultiPolygon"""
        self.logger.section("15. Конвертация Polygon -> MultiPolygon")
        if not self.manager:
            self.logger.fail("Менеджер не инициализирован (пропуск)")
            return

        try:
            # Единственный полигон должен стать MultiPolygon
            layer = self._create_polygon_layer(
                "L_1_12_1_conv",
                ["POLYGON((0 0, 50 0, 50 50, 0 50, 0 0))"]
            )

            united, crs = self.manager._collect_and_unite_geometries([layer])

            if united and not united.isEmpty():
                wkb_type = united.wkbType()
                is_multi = united.isMultipart()
                self.logger.check(
                    is_multi,
                    f"Результат MultiPolygon (wkbType={wkb_type})",
                    f"Результат не MultiPolygon (wkbType={wkb_type}, isMulti={is_multi})"
                )
            else:
                self.logger.fail("Объединённая геометрия пуста")

        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")
