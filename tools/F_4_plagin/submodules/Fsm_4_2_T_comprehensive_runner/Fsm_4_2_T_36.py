# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_36 - Тесты для M_36 LandCategoryAssignmentManager

Тестирует:
- Инициализацию менеджера
- Каскадные константы (слои, категории, fallback)
- assign_land_category: пустой вход, отсутствие зональных слоёв
- _determine_category: пустая геометрия -> fallback
- Структуру результата (attrs['План_категория'])
- CRS трансформацию для зональных слоёв в разных CRS (EPSG:3857 vs локальная МСК)
"""

from qgis.core import QgsGeometry, QgsPointXY


class TestM36:
    """Тесты для M_36_LandCategoryAssignmentManager"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.manager = None

    def run_all_tests(self):
        """Запуск всех тестов M_36"""
        self.logger.section("ТЕСТ M_36: LandCategoryAssignmentManager")

        try:
            # Инициализация
            self.test_01_init()
            self.test_02_cascade_constants()
            self.test_03_fallback_category()

            # assign_land_category
            self.test_04_empty_input()
            self.test_05_none_geometry()
            self.test_06_empty_geometry()
            self.test_07_plan_category_field_set()
            self.test_08_no_zone_layers_fallback()
            self.test_09_multiple_features()

            # _determine_category
            self.test_10_determine_empty_centroid()

            # CRS трансформация (новый функционал)
            self.test_11_crs_transform_import()
            self.test_12_load_zone_layers_structure()
            self.test_13_determine_category_with_empty_zones()

        except Exception as e:
            self.logger.error(f"Критическая ошибка: {e}")

        self.logger.summary()

    # --- Инициализация ---

    def test_01_init(self):
        """ТЕСТ 1: Инициализация менеджера"""
        self.logger.section("1. Инициализация LandCategoryAssignmentManager")
        try:
            from Daman_QGIS.managers import LandCategoryAssignmentManager
            self.manager = LandCategoryAssignmentManager()

            self.logger.check(
                self.manager is not None,
                "LandCategoryAssignmentManager создан",
                "LandCategoryAssignmentManager не создан!"
            )

            # Проверяем методы
            for method in ['assign_land_category', '_determine_category', '_load_zone_layers']:
                self.logger.check(
                    hasattr(self.manager, method),
                    f"Метод {method}() существует",
                    f"Метод {method}() отсутствует!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка создания: {e}")

    def test_02_cascade_constants(self):
        """ТЕСТ 2: Каскадные константы"""
        self.logger.section("2. Каскадные константы")
        try:
            from Daman_QGIS.managers.validation.M_36_land_category_assignment_manager import (
                _CATEGORY_CASCADE, _LAYER_NP, _LAYER_OOPT, _LAYER_LES,
            )

            self.logger.check(
                len(_CATEGORY_CASCADE) == 3,
                f"3 уровня каскада",
                f"Ожидалось 3, получено {len(_CATEGORY_CASCADE)}"
            )

            # Проверяем порядок приоритетов
            self.logger.check(
                _CATEGORY_CASCADE[0]['layer_name'] == _LAYER_NP,
                "Приоритет 1: НП (населённые пункты)",
                f"Приоритет 1: '{_CATEGORY_CASCADE[0]['layer_name']}'!"
            )
            self.logger.check(
                _CATEGORY_CASCADE[1]['layer_name'] == _LAYER_OOPT,
                "Приоритет 2: ООПТ",
                f"Приоритет 2: '{_CATEGORY_CASCADE[1]['layer_name']}'!"
            )
            self.logger.check(
                _CATEGORY_CASCADE[2]['layer_name'] == _LAYER_LES,
                "Приоритет 3: Лесной фонд",
                f"Приоритет 3: '{_CATEGORY_CASCADE[2]['layer_name']}'!"
            )

            # Проверяем категории
            categories = [item['category'] for item in _CATEGORY_CASCADE]
            self.logger.check(
                'Земли населённых пунктов' in categories,
                "Категория НП присутствует",
                "Категория НП отсутствует!"
            )
            self.logger.check(
                'Земли лесного фонда' in categories,
                "Категория лесного фонда присутствует",
                "Категория лесного фонда отсутствует!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_03_fallback_category(self):
        """ТЕСТ 3: Fallback категория"""
        self.logger.section("3. Fallback категория")
        try:
            from Daman_QGIS.managers.validation.M_36_land_category_assignment_manager import (
                _FALLBACK_CATEGORY,
            )

            self.logger.check(
                'промышленности' in _FALLBACK_CATEGORY.lower(),
                "Fallback содержит 'промышленности'",
                f"Fallback: '{_FALLBACK_CATEGORY[:50]}...'"
            )
            self.logger.check(
                len(_FALLBACK_CATEGORY) > 50,
                f"Fallback: полный текст ({len(_FALLBACK_CATEGORY)} символов)",
                f"Fallback слишком короткий: {len(_FALLBACK_CATEGORY)}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- assign_land_category ---

    def test_04_empty_input(self):
        """ТЕСТ 4: Пустой список features_data"""
        self.logger.section("4. Пустой вход")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return

        try:
            result = self.manager.assign_land_category([])
            self.logger.check(
                result == [],
                "Пустой вход -> пустой результат",
                f"Пустой вход -> {result}"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_05_none_geometry(self):
        """ТЕСТ 5: Feature с geometry=None"""
        self.logger.section("5. Feature с geometry=None")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return

        try:
            from Daman_QGIS.managers.validation.M_36_land_category_assignment_manager import (
                _FALLBACK_CATEGORY,
            )

            features = [{'geometry': None, 'attributes': {'ID': '1'}}]
            result = self.manager.assign_land_category(features)

            self.logger.check(
                len(result) == 1,
                "1 feature обработан",
                f"Ожидалось 1, получено {len(result)}"
            )
            self.logger.check(
                result[0]['attributes']['План_категория'] == _FALLBACK_CATEGORY,
                "None geometry -> fallback категория",
                f"None geometry -> '{result[0]['attributes'].get('План_категория', 'NOT SET')[:50]}...'"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_06_empty_geometry(self):
        """ТЕСТ 6: Feature с пустой геометрией"""
        self.logger.section("6. Feature с пустой геометрией")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return

        try:
            from Daman_QGIS.managers.validation.M_36_land_category_assignment_manager import (
                _FALLBACK_CATEGORY,
            )

            empty_geom = QgsGeometry()
            features = [{'geometry': empty_geom, 'attributes': {'ID': '2'}}]
            result = self.manager.assign_land_category(features)

            self.logger.check(
                result[0]['attributes']['План_категория'] == _FALLBACK_CATEGORY,
                "Пустая геометрия -> fallback категория",
                f"Пустая геометрия -> '{result[0]['attributes'].get('План_категория', 'NOT SET')[:50]}...'"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_07_plan_category_field_set(self):
        """ТЕСТ 7: Поле План_категория устанавливается"""
        self.logger.section("7. Поле План_категория")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return

        try:
            # Простой полигон (без зональных слоёв -> fallback)
            geom = QgsGeometry.fromPolygonXY([[
                QgsPointXY(0, 0), QgsPointXY(1, 0),
                QgsPointXY(1, 1), QgsPointXY(0, 1),
                QgsPointXY(0, 0)
            ]])
            features = [{'geometry': geom, 'attributes': {}}]
            result = self.manager.assign_land_category(features)

            self.logger.check(
                'План_категория' in result[0]['attributes'],
                "Поле План_категория установлено",
                "Поле План_категория не установлено!"
            )
            self.logger.check(
                isinstance(result[0]['attributes']['План_категория'], str),
                "План_категория: строковое значение",
                f"План_категория: тип {type(result[0]['attributes']['План_категория'])}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_08_no_zone_layers_fallback(self):
        """ТЕСТ 8: Без зональных слоёв -> все fallback"""
        self.logger.section("8. Без зональных слоёв -> fallback")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return

        try:
            from Daman_QGIS.managers.validation.M_36_land_category_assignment_manager import (
                _FALLBACK_CATEGORY,
            )

            geom = QgsGeometry.fromPolygonXY([[
                QgsPointXY(10, 10), QgsPointXY(11, 10),
                QgsPointXY(11, 11), QgsPointXY(10, 11),
                QgsPointXY(10, 10)
            ]])
            features = [{'geometry': geom, 'attributes': {'ID': '3'}}]
            result = self.manager.assign_land_category(features)

            # Без зональных слоёв в проекте все получают fallback
            self.logger.check(
                result[0]['attributes']['План_категория'] == _FALLBACK_CATEGORY,
                "Без зональных слоёв -> fallback",
                f"Без зональных слоёв -> '{result[0]['attributes']['План_категория'][:40]}...'"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_09_multiple_features(self):
        """ТЕСТ 9: Несколько features одновременно"""
        self.logger.section("9. Batch обработка")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return

        try:
            features = []
            for i in range(5):
                geom = QgsGeometry.fromPolygonXY([[
                    QgsPointXY(i, 0), QgsPointXY(i + 1, 0),
                    QgsPointXY(i + 1, 1), QgsPointXY(i, 1),
                    QgsPointXY(i, 0)
                ]])
                features.append({'geometry': geom, 'attributes': {'ID': str(i)}})

            result = self.manager.assign_land_category(features)

            self.logger.check(
                len(result) == 5,
                "5 features обработаны",
                f"Ожидалось 5, получено {len(result)}"
            )

            # Все должны иметь План_категория
            all_have = all('План_категория' in f['attributes'] for f in result)
            self.logger.check(
                all_have,
                "Все features имеют План_категория",
                "Не все features имеют План_категория!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- _determine_category ---

    def test_10_determine_empty_centroid(self):
        """ТЕСТ 10: _determine_category с пустой геометрией"""
        self.logger.section("10. _determine_category с пустой геометрией")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return

        try:
            from Daman_QGIS.managers.validation.M_36_land_category_assignment_manager import (
                _FALLBACK_CATEGORY,
            )

            # Пустая геометрия (не может вычислить центроид)
            empty_geom = QgsGeometry()
            category = self.manager._determine_category(empty_geom, [], feature_id='test')

            self.logger.check(
                category == _FALLBACK_CATEGORY,
                "Пустая геометрия -> fallback",
                f"Пустая геометрия -> '{category[:40]}...'"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- CRS трансформация (новый функционал) ---

    def test_11_crs_transform_import(self):
        """ТЕСТ 11: Импорт QgsCoordinateTransform в M_36"""
        self.logger.section("11. CRS трансформация - импорт")
        try:
            from Daman_QGIS.managers.validation.M_36_land_category_assignment_manager import (
                QgsCoordinateTransform,
            )

            self.logger.check(
                QgsCoordinateTransform is not None,
                "QgsCoordinateTransform импортирован в M_36",
                "QgsCoordinateTransform НЕ импортирован!"
            )

        except ImportError as e:
            self.logger.error(f"QgsCoordinateTransform не импортирован в M_36: {e}")

    def test_12_load_zone_layers_structure(self):
        """ТЕСТ 12: _load_zone_layers возвращает корректную структуру с transform"""
        self.logger.section("12. _load_zone_layers структура с transform")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return

        try:
            from qgis.core import QgsCoordinateReferenceSystem

            # Тест с локальной CRS
            local_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            zone_layers = self.manager._load_zone_layers(local_crs)

            # Метод должен возвращать список (даже пустой)
            self.logger.check(
                isinstance(zone_layers, list),
                "_load_zone_layers возвращает список",
                f"_load_zone_layers возвращает {type(zone_layers)}"
            )

            # Если слои найдены, проверяем структуру
            if zone_layers:
                first_zone = zone_layers[0]
                required_keys = ['layer', 'category', 'index', 'layer_name', 'transform']

                for key in required_keys:
                    self.logger.check(
                        key in first_zone,
                        f"zone_layer содержит ключ '{key}'",
                        f"zone_layer НЕ содержит ключ '{key}'!"
                    )
            else:
                self.logger.info("Зональные слои не найдены в проекте (ожидаемо для теста)")

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_13_determine_category_with_empty_zones(self):
        """ТЕСТ 13: _determine_category работает без исключений с пустыми zones"""
        self.logger.section("13. _determine_category с пустыми zones")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return

        try:
            # Геометрия в EPSG:4326
            geom = QgsGeometry.fromPolygonXY([[
                QgsPointXY(37.0, 55.0), QgsPointXY(37.1, 55.0),
                QgsPointXY(37.1, 55.1), QgsPointXY(37.0, 55.1),
                QgsPointXY(37.0, 55.0)
            ]])

            # Должен работать без исключений с пустыми zone_layers
            category = self.manager._determine_category(geom, [], feature_id='test_crs')

            self.logger.check(
                isinstance(category, str),
                "Категория определена (строка)",
                f"Категория не строка: {type(category)}"
            )
            self.logger.check(
                len(category) > 0,
                "Категория не пустая",
                "Категория пустая!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")


def run_tests(iface, logger):
    """Точка входа для запуска тестов"""
    test = TestM36(iface, logger)
    test.run_all_tests()
    return test
