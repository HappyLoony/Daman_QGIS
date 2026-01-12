# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_2_4 - Тест функции F_2_4_ГПМТ
Проверка формирования границ проекта межевания территории
"""


class TestF24:
    """Тесты для функции F_2_4_GPMT"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.module = None

    def run_all_tests(self):
        """Запуск всех тестов F_2_4"""
        self.logger.section("ТЕСТ F_2_4: Формирование ГПМТ")

        try:
            self.test_01_init_module()
            self.test_02_check_dependencies()
            self.test_03_zpr_layers()
            self.test_04_processing_algorithms()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов F_2_4: {str(e)}")

        self.logger.summary()

    def test_01_init_module(self):
        """ТЕСТ 1: Инициализация модуля F_2_4"""
        self.logger.section("1. Инициализация F_2_4_GPMT")

        try:
            from Daman_QGIS.tools.F_2_processing.F_2_4_gpmt import F_2_4_GPMT

            self.module = F_2_4_GPMT(self.iface)
            self.logger.success("Модуль F_2_4_GPMT загружен")

            # Проверяем наличие методов
            self.logger.check(
                hasattr(self.module, 'run'),
                "Метод run существует",
                "Метод run отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, '_find_zpr_layers'),
                "Метод _find_zpr_layers существует",
                "Метод _find_zpr_layers отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, '_merge_zpr_layers'),
                "Метод _merge_zpr_layers существует",
                "Метод _merge_zpr_layers отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, '_create_gpmt_layer'),
                "Метод _create_gpmt_layer существует",
                "Метод _create_gpmt_layer отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, '_save_to_gpkg'),
                "Метод _save_to_gpkg существует",
                "Метод _save_to_gpkg отсутствует!"
            )

            # Проверяем имя модуля
            if hasattr(self.module, 'get_name'):
                name = self.module.get_name()
                self.logger.check(
                    "2_4" in name or "ГПМТ" in name,
                    f"Имя модуля корректное: '{name}'",
                    f"Имя модуля некорректное: '{name}'"
                )

        except Exception as e:
            self.logger.error(f"Ошибка инициализации: {str(e)}")
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
            # Проверяем BaseTool
            from Daman_QGIS.core.base_tool import BaseTool
            self.logger.success("BaseTool доступен")

            # Проверяем utils
            from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
            self.logger.success("utils (log_*) доступны")

            # Проверяем QGIS processing
            from qgis import processing
            self.logger.success("qgis.processing доступен")

            # Проверяем StyleManager
            from Daman_QGIS.managers import StyleManager
            self.logger.success("StyleManager доступен")

        except Exception as e:
            self.logger.error(f"Ошибка проверки зависимостей: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_03_zpr_layers(self):
        """ТЕСТ 3: Проверка поиска слоёв ЗПР"""
        self.logger.section("3. Проверка поиска слоёв ЗПР")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            # Ищем слои ЗПР
            zpr_layers = self.module._find_zpr_layers()

            self.logger.info(f"Найдено слоёв ЗПР: {len(zpr_layers)}")

            if zpr_layers:
                for layer in zpr_layers:
                    self.logger.info(f"  - {layer.name()}: {layer.featureCount()} объектов")
                self.logger.success("Слои ЗПР найдены")
            else:
                # Это нормально если проект не содержит ЗПР
                self.logger.warning("Слои ЗПР не найдены (требуется импорт ЗПР)")

        except Exception as e:
            self.logger.warning(f"Не удалось найти слои ЗПР: {str(e)[:100]}")

    def test_04_processing_algorithms(self):
        """ТЕСТ 4: Проверка доступности алгоритмов обработки"""
        self.logger.section("4. Проверка алгоритмов обработки")

        try:
            from qgis import processing

            # Проверяем алгоритмы которые использует модуль
            algorithms = ['native:union', 'native:dissolve']

            for alg_name in algorithms:
                try:
                    alg = processing.algorithmHelp(alg_name)
                    if alg:
                        self.logger.success(f"Алгоритм {alg_name} доступен")
                    else:
                        self.logger.warning(f"Алгоритм {alg_name} не вернул справку")
                except Exception:
                    # Если algorithmHelp не работает, попробуем другой способ
                    try:
                        from qgis.core import QgsApplication
                        registry = QgsApplication.processingRegistry()
                        if registry.algorithmById(alg_name):
                            self.logger.success(f"Алгоритм {alg_name} доступен")
                        else:
                            self.logger.warning(f"Алгоритм {alg_name} не найден")
                    except Exception as e2:
                        self.logger.warning(f"Алгоритм {alg_name}: ошибка проверки - {str(e2)[:50]}")

        except Exception as e:
            self.logger.error(f"Ошибка проверки алгоритмов: {str(e)}")
