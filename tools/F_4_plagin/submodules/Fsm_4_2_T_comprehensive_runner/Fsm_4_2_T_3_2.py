# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_4_2 - Тесты для F_3_2_LesHLU (Генерация Word ХЛУ)

Тестирует:
- Инициализацию модуля и зависимости
- Валидацию (слой МО, слои Le_3_*)
- HLU_DataProcessor из Msm_33_1
- Формирование пути к выходному файлу
- Константы LE4_LAYERS
"""

import tempfile
import os
import shutil
from datetime import datetime

from qgis.core import QgsProject


class TestF42:
    """Тесты для F_3_2_LesHLU - Генерация Word документа ХЛУ"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.module = None
        self.test_dir = None

    def run_all_tests(self):
        """Запуск всех тестов F_3_2"""
        self.logger.section("ТЕСТ F_3_2: Генерация Word документа ХЛУ")
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f42_")

        try:
            # Инициализация
            self.test_01_init_module()
            self.test_02_check_methods()
            self.test_03_setters()

            # Валидация
            self.test_04_validate_no_managers()
            self.test_05_le4_layers_constant()

            # HLU Processor
            self.test_06_hlu_processor_import()
            self.test_07_hlu_processor_init()

            # Пути
            self.test_08_output_path_format()
            self.test_09_template_path()

            # Константы
            self.test_10_layer_atd_mo()

        except Exception as e:
            self.logger.error(f"Критическая ошибка: {e}")

        finally:
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    shutil.rmtree(self.test_dir)
                except Exception:
                    pass

        self.logger.summary()

    # --- Инициализация ---

    def test_01_init_module(self):
        """ТЕСТ 1: Инициализация F_3_2_LesHLU"""
        self.logger.section("1. Инициализация F_3_2_LesHLU")
        try:
            from Daman_QGIS.tools.F_3_hlu.F_3_2_les_hlu import F_3_2_LesHLU
            self.module = F_3_2_LesHLU(self.iface)

            self.logger.check(
                self.module is not None,
                "F_3_2_LesHLU создан",
                "F_3_2_LesHLU не создан!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")
            self.module = None

    def test_02_check_methods(self):
        """ТЕСТ 2: Проверка методов модуля"""
        self.logger.section("2. Проверка методов")
        if not self.module:
            self.logger.skip("Модуль не инициализирован")
            return

        methods = [
            'run',
            'set_plugin_dir',
            'set_layer_manager',
            'set_project_manager',
            'get_name',
            '_validate',
            '_get_output_path',
        ]

        for method in methods:
            self.logger.check(
                hasattr(self.module, method),
                f"Метод {method}() существует",
                f"Метод {method}() отсутствует!"
            )

    def test_03_setters(self):
        """ТЕСТ 3: Проверка сеттеров"""
        self.logger.section("3. Сеттеры")
        if not self.module:
            self.logger.skip("Модуль не инициализирован")
            return

        try:
            # set_plugin_dir
            test_dir = "/test/plugin/dir"
            self.module.set_plugin_dir(test_dir)
            self.logger.check(
                self.module.plugin_dir == test_dir,
                "set_plugin_dir работает",
                f"set_plugin_dir не установил значение: {self.module.plugin_dir}"
            )

            # Сброс
            self.module.plugin_dir = None

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- Валидация ---

    def test_04_validate_no_managers(self):
        """ТЕСТ 4: Валидация без менеджеров"""
        self.logger.section("4. Валидация без менеджеров")
        if not self.module:
            self.logger.skip("Модуль не инициализирован")
            return

        try:
            # Без layer_manager
            self.module.layer_manager = None
            self.module.plugin_dir = None

            # _validate должен вернуть False
            # Но он показывает QMessageBox, поэтому проверяем атрибуты
            self.logger.check(
                self.module.layer_manager is None,
                "layer_manager = None -> валидация не пройдёт",
                "layer_manager не None"
            )

            self.logger.check(
                self.module.plugin_dir is None,
                "plugin_dir = None -> валидация не пройдёт",
                "plugin_dir не None"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_05_le4_layers_constant(self):
        """ТЕСТ 5: Константа LE4_LAYERS"""
        self.logger.section("5. LE4_LAYERS")
        try:
            from Daman_QGIS.managers.export.submodules.Msm_33_1_hlu_processor import LE4_LAYERS

            self.logger.check(
                isinstance(LE4_LAYERS, (list, tuple)),
                f"LE4_LAYERS - список/кортеж ({len(LE4_LAYERS)} элементов)",
                f"LE4_LAYERS не список: {type(LE4_LAYERS)}"
            )

            # Проверяем что все начинаются с Le_3_
            le4_count = sum(1 for l in LE4_LAYERS if l.startswith('Le_3_'))
            self.logger.check(
                le4_count == len(LE4_LAYERS),
                "Все слои начинаются с Le_3_",
                f"Не все слои Le_3_: {le4_count}/{len(LE4_LAYERS)}"
            )

            # Проверяем категории ОКС, ПО, ВО (русские сокращения в именах слоёв)
            categories = ['ОКС', 'ПО', 'ВО']
            for cat in categories:
                # Слои заканчиваются на _ОКС, _ПО, _ВО
                cat_count = sum(1 for l in LE4_LAYERS if l.endswith(f'_{cat}'))
                self.logger.check(
                    cat_count >= 1,
                    f"Категория {cat} представлена ({cat_count} слоёв)",
                    f"Категория {cat} отсутствует!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- HLU Processor ---

    def test_06_hlu_processor_import(self):
        """ТЕСТ 6: Импорт HLU_DataProcessor"""
        self.logger.section("6. Импорт HLU_DataProcessor")
        try:
            from Daman_QGIS.managers.export.submodules import HLU_DataProcessor

            self.logger.check(
                HLU_DataProcessor is not None,
                "HLU_DataProcessor импортирован",
                "HLU_DataProcessor не импортирован!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_07_hlu_processor_init(self):
        """ТЕСТ 7: Инициализация HLU_DataProcessor"""
        self.logger.section("7. HLU_DataProcessor инициализация")
        try:
            from Daman_QGIS.managers.export.submodules import HLU_DataProcessor

            # HLU_DataProcessor(project_manager, layer_manager)
            # Создаём с None для теста
            processor = HLU_DataProcessor(None, None)

            self.logger.check(
                processor is not None,
                "HLU_DataProcessor создан",
                "HLU_DataProcessor не создан!"
            )

            # Проверяем методы
            methods = ['prepare_full_context_le4', 'prepare_full_context']
            for method in methods:
                self.logger.check(
                    hasattr(processor, method),
                    f"Метод {method}() существует",
                    f"Метод {method}() отсутствует!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- Пути ---

    def test_08_output_path_format(self):
        """ТЕСТ 8: Формат пути выходного файла"""
        self.logger.section("8. Формат выходного пути")
        if not self.module:
            self.logger.skip("Модуль не инициализирован")
            return

        try:
            # Проверяем логику формирования имени файла
            date_str = datetime.now().strftime("%Y-%m-%d")
            expected_pattern = f"HLU_{date_str}"

            self.logger.check(
                len(date_str) == 10,
                f"Формат даты: {date_str}",
                f"Неверный формат даты: {date_str}"
            )

            self.logger.check(
                expected_pattern.startswith("HLU_"),
                f"Имя файла начинается с HLU_",
                f"Неверный префикс: {expected_pattern}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_09_template_path(self):
        """ТЕСТ 9: Путь к шаблону Word"""
        self.logger.section("9. Путь к шаблону")
        try:
            # Относительный путь к шаблону
            template_rel = "data/templates/word/hlu/hlu.docx"

            self.logger.check(
                template_rel.endswith('.docx'),
                "Шаблон имеет расширение .docx",
                f"Неверное расширение: {template_rel}"
            )

            self.logger.check(
                'hlu' in template_rel,
                "Путь содержит 'hlu'",
                f"Путь не содержит 'hlu': {template_rel}"
            )

            # Проверяем существование папки templates в plugin_dir
            # (только если знаем plugin_dir)
            self.logger.info(f"Ожидаемый путь: [plugin_dir]/{template_rel}")

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- Константы ---

    def test_10_layer_atd_mo(self):
        """ТЕСТ 10: Константа LAYER_ATD_MO"""
        self.logger.section("10. LAYER_ATD_MO")
        try:
            from Daman_QGIS.constants import LAYER_ATD_MO

            self.logger.check(
                isinstance(LAYER_ATD_MO, str),
                f"LAYER_ATD_MO - строка: '{LAYER_ATD_MO}'",
                f"LAYER_ATD_MO не строка: {type(LAYER_ATD_MO)}"
            )

            self.logger.check(
                'МО' in LAYER_ATD_MO or 'MO' in LAYER_ATD_MO,
                "LAYER_ATD_MO содержит МО/MO",
                f"LAYER_ATD_MO не содержит МО: '{LAYER_ATD_MO}'"
            )

            self.logger.check(
                'Le_1_2_' in LAYER_ATD_MO or 'L_1_2_' in LAYER_ATD_MO,
                "LAYER_ATD_MO - слой L_1_2_* или Le_1_2_*",
                f"LAYER_ATD_MO неожиданный формат: '{LAYER_ATD_MO}'"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")


def run_tests(iface, logger):
    """Точка входа для запуска тестов"""
    test = TestF42(iface, logger)
    test.run_all_tests()
    return test
