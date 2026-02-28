# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_utils_refresh - Тесты для функций safe_refresh в utils.py

Тестирует:
- safe_refresh_layer(): безопасный triggerRepaint через QTimer
- safe_refresh_canvas(): безопасный refresh canvas с уровнями
- safe_refresh_layer_symbology(): безопасное обновление символики
- Константы REFRESH_LIGHT, REFRESH_MEDIUM, REFRESH_HEAVY, REFRESH_FULL
"""

from qgis.core import QgsVectorLayer, QgsProject
from qgis.PyQt.QtCore import QTimer


class TestUtilsRefresh:
    """Тесты для функций safe_refresh в utils.py"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.test_layer = None

    def run_all_tests(self):
        """Запуск всех тестов utils refresh"""
        self.logger.section("ТЕСТ utils: safe_refresh функции")

        try:
            self.test_01_import_constants()
            self.test_02_import_functions()
            self.test_03_refresh_constants_values()
            self.test_04_safe_refresh_layer_none()
            self.test_05_safe_refresh_layer_valid()
            self.test_06_safe_refresh_canvas_levels()
            self.test_07_safe_refresh_layer_symbology_none()
            self.test_08_safe_refresh_layer_symbology_valid()
            self.test_09_qtimer_usage()

        except Exception as e:
            self.logger.error(f"Критическая ошибка: {e}")

        self.logger.summary()

    def _create_test_layer(self):
        """Создать тестовый memory layer"""
        if self.test_layer is None:
            self.test_layer = QgsVectorLayer(
                "Polygon?crs=EPSG:4326",
                "test_refresh_layer",
                "memory"
            )
        return self.test_layer

    # --- Импорт ---

    def test_01_import_constants(self):
        """ТЕСТ 1: Импорт констант REFRESH_*"""
        self.logger.section("1. Импорт констант REFRESH_*")
        try:
            from Daman_QGIS.utils import (
                REFRESH_LIGHT, REFRESH_MEDIUM, REFRESH_HEAVY, REFRESH_FULL
            )

            self.logger.check(
                REFRESH_LIGHT is not None,
                "REFRESH_LIGHT импортирован",
                "REFRESH_LIGHT не импортирован!"
            )
            self.logger.check(
                REFRESH_MEDIUM is not None,
                "REFRESH_MEDIUM импортирован",
                "REFRESH_MEDIUM не импортирован!"
            )
            self.logger.check(
                REFRESH_HEAVY is not None,
                "REFRESH_HEAVY импортирован",
                "REFRESH_HEAVY не импортирован!"
            )
            self.logger.check(
                REFRESH_FULL is not None,
                "REFRESH_FULL импортирован",
                "REFRESH_FULL не импортирован!"
            )

        except ImportError as e:
            self.logger.error(f"Ошибка импорта констант: {e}")

    def test_02_import_functions(self):
        """ТЕСТ 2: Импорт функций safe_refresh_*"""
        self.logger.section("2. Импорт функций safe_refresh_*")
        try:
            from Daman_QGIS.utils import (
                safe_refresh_layer,
                safe_refresh_canvas,
                safe_refresh_layer_symbology
            )

            self.logger.check(
                callable(safe_refresh_layer),
                "safe_refresh_layer: callable",
                "safe_refresh_layer: не callable!"
            )
            self.logger.check(
                callable(safe_refresh_canvas),
                "safe_refresh_canvas: callable",
                "safe_refresh_canvas: не callable!"
            )
            self.logger.check(
                callable(safe_refresh_layer_symbology),
                "safe_refresh_layer_symbology: callable",
                "safe_refresh_layer_symbology: не callable!"
            )

        except ImportError as e:
            self.logger.error(f"Ошибка импорта функций: {e}")

    def test_03_refresh_constants_values(self):
        """ТЕСТ 3: Значения констант REFRESH_*"""
        self.logger.section("3. Значения констант REFRESH_*")
        try:
            from Daman_QGIS.utils import (
                REFRESH_LIGHT, REFRESH_MEDIUM, REFRESH_HEAVY, REFRESH_FULL
            )

            # Проверка порядка (возрастание "тяжести")
            self.logger.check(
                REFRESH_LIGHT < REFRESH_MEDIUM < REFRESH_HEAVY < REFRESH_FULL,
                "Порядок: LIGHT < MEDIUM < HEAVY < FULL",
                f"Неверный порядок: {REFRESH_LIGHT}, {REFRESH_MEDIUM}, {REFRESH_HEAVY}, {REFRESH_FULL}"
            )

            # Конкретные значения
            self.logger.check(
                REFRESH_LIGHT == 1,
                f"REFRESH_LIGHT = 1",
                f"REFRESH_LIGHT = {REFRESH_LIGHT}"
            )
            self.logger.check(
                REFRESH_MEDIUM == 2,
                f"REFRESH_MEDIUM = 2",
                f"REFRESH_MEDIUM = {REFRESH_MEDIUM}"
            )
            self.logger.check(
                REFRESH_HEAVY == 3,
                f"REFRESH_HEAVY = 3",
                f"REFRESH_HEAVY = {REFRESH_HEAVY}"
            )
            self.logger.check(
                REFRESH_FULL == 4,
                f"REFRESH_FULL = 4",
                f"REFRESH_FULL = {REFRESH_FULL}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- safe_refresh_layer ---

    def test_04_safe_refresh_layer_none(self):
        """ТЕСТ 4: safe_refresh_layer с None"""
        self.logger.section("4. safe_refresh_layer с None")
        try:
            from Daman_QGIS.utils import safe_refresh_layer

            # Не должен вызывать исключение
            safe_refresh_layer(None)
            self.logger.check(
                True,
                "safe_refresh_layer(None): без исключений",
                "safe_refresh_layer(None): исключение!"
            )

        except Exception as e:
            self.logger.error(f"safe_refresh_layer(None) вызвал исключение: {e}")

    def test_05_safe_refresh_layer_valid(self):
        """ТЕСТ 5: safe_refresh_layer с валидным слоем"""
        self.logger.section("5. safe_refresh_layer с валидным слоем")
        try:
            from Daman_QGIS.utils import safe_refresh_layer

            layer = self._create_test_layer()

            self.logger.check(
                layer.isValid(),
                "Тестовый слой валиден",
                "Тестовый слой невалиден!"
            )

            # Не должен вызывать исключение
            safe_refresh_layer(layer)
            safe_refresh_layer(layer, delay_ms=100)

            self.logger.check(
                True,
                "safe_refresh_layer(layer): без исключений",
                "safe_refresh_layer(layer): исключение!"
            )

        except Exception as e:
            self.logger.error(f"safe_refresh_layer с валидным слоем: {e}")

    # --- safe_refresh_canvas ---

    def test_06_safe_refresh_canvas_levels(self):
        """ТЕСТ 6: safe_refresh_canvas с разными уровнями"""
        self.logger.section("6. safe_refresh_canvas с разными уровнями")
        try:
            from Daman_QGIS.utils import (
                safe_refresh_canvas,
                REFRESH_LIGHT, REFRESH_MEDIUM, REFRESH_HEAVY, REFRESH_FULL
            )

            # Все уровни не должны вызывать исключений
            levels = [REFRESH_LIGHT, REFRESH_MEDIUM, REFRESH_HEAVY, REFRESH_FULL]
            for level in levels:
                try:
                    safe_refresh_canvas(level)
                    self.logger.check(
                        True,
                        f"safe_refresh_canvas({level}): OK",
                        f"safe_refresh_canvas({level}): исключение!"
                    )
                except Exception as e:
                    self.logger.error(f"safe_refresh_canvas({level}): {e}")

            # Проверка delay_ms
            safe_refresh_canvas(REFRESH_MEDIUM, delay_ms=200)
            self.logger.check(
                True,
                "safe_refresh_canvas с delay_ms=200: OK",
                "safe_refresh_canvas с delay_ms: исключение!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- safe_refresh_layer_symbology ---

    def test_07_safe_refresh_layer_symbology_none(self):
        """ТЕСТ 7: safe_refresh_layer_symbology с None"""
        self.logger.section("7. safe_refresh_layer_symbology с None")
        try:
            from Daman_QGIS.utils import safe_refresh_layer_symbology

            # Не должен вызывать исключение
            safe_refresh_layer_symbology(None)
            self.logger.check(
                True,
                "safe_refresh_layer_symbology(None): без исключений",
                "safe_refresh_layer_symbology(None): исключение!"
            )

        except Exception as e:
            self.logger.error(f"safe_refresh_layer_symbology(None): {e}")

    def test_08_safe_refresh_layer_symbology_valid(self):
        """ТЕСТ 8: safe_refresh_layer_symbology с валидным слоем"""
        self.logger.section("8. safe_refresh_layer_symbology с валидным слоем")
        try:
            from Daman_QGIS.utils import safe_refresh_layer_symbology

            layer = self._create_test_layer()

            # Добавляем слой в проект для проверки symbology
            QgsProject.instance().addMapLayer(layer, False)

            # Не должен вызывать исключение
            safe_refresh_layer_symbology(layer)
            safe_refresh_layer_symbology(layer, delay_ms=100)

            self.logger.check(
                True,
                "safe_refresh_layer_symbology(layer): без исключений",
                "safe_refresh_layer_symbology(layer): исключение!"
            )

            # Убираем тестовый слой
            QgsProject.instance().removeMapLayer(layer.id())

        except Exception as e:
            self.logger.error(f"safe_refresh_layer_symbology с валидным слоем: {e}")

    def test_09_qtimer_usage(self):
        """ТЕСТ 9: Проверка использования QTimer.singleShot"""
        self.logger.section("9. Использование QTimer.singleShot")
        try:
            import inspect
            from Daman_QGIS.utils import (
                safe_refresh_layer,
                safe_refresh_canvas,
                safe_refresh_layer_symbology
            )

            # Проверяем, что функции используют QTimer
            for func in [safe_refresh_layer, safe_refresh_canvas, safe_refresh_layer_symbology]:
                source = inspect.getsource(func)
                uses_qtimer = 'QTimer.singleShot' in source or 'QTimer' in source

                self.logger.check(
                    uses_qtimer,
                    f"{func.__name__}: использует QTimer",
                    f"{func.__name__}: НЕ использует QTimer!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка проверки QTimer: {e}")


def run_tests(iface, logger):
    """Точка входа для запуска тестов"""
    test = TestUtilsRefresh(iface, logger)
    test.run_all_tests()
    return test
