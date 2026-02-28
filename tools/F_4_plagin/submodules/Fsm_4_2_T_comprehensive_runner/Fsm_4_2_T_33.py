# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_33 - Тесты для M_33 WordExportManager

Тестирует:
- Инициализацию менеджера
- Работу с шаблонами (list, exists, validate)
- Рендеринг документов
- Форматирование данных
- Обработку ошибок
"""

import os
import tempfile
import shutil
from pathlib import Path


class TestM33:
    """Тесты для M_33_WordExportManager"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.manager = None
        self.test_dir = None
        self.template_dir = None
        self.docxtpl_available = False

    def run_all_tests(self):
        """Запуск всех тестов M_33"""
        self.logger.section("ТЕСТ M_33: WordExportManager")

        # Создаем временные директории
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_word_")
        self.template_dir = os.path.join(self.test_dir, "templates")
        os.makedirs(self.template_dir, exist_ok=True)
        self.logger.info(f"Временная директория: {self.test_dir}")

        try:
            # Проверка доступности docxtpl
            self.test_00_check_docxtpl()

            # Тесты инициализации
            self.test_01_init_manager()
            self.test_02_init_creates_missing_dir()

            # Тесты работы с шаблонами
            self.test_03_list_templates_empty()
            self.test_04_template_exists()
            self.test_05_get_template_path()

            # Тесты форматирования
            self.test_06_format_area()
            self.test_07_format_area_zapas()

            # Тесты валидации (требуют docxtpl)
            if self.docxtpl_available:
                self.test_08_validate_template_missing()
                self.test_09_validate_template_not_docx()
                self.test_10_render_missing_template()

            # Тесты кэширования
            self.test_11_clear_cache()

            # Тесты синглтона
            self.test_12_singleton()

        finally:
            # Очистка временных файлов
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    shutil.rmtree(self.test_dir)
                    self.logger.info("Временные файлы очищены")
                except Exception as e:
                    self.logger.warning(f"Не удалось удалить временные файлы: {str(e)}")

        # Итоговая сводка
        self.logger.summary()

    def test_00_check_docxtpl(self):
        """ТЕСТ 0: Проверка доступности docxtpl"""
        self.logger.section("0. Проверка библиотеки docxtpl")

        try:
            from docxtpl import DocxTemplate
            self.docxtpl_available = True
            self.logger.success("Библиотека docxtpl доступна")
        except ImportError:
            self.docxtpl_available = False
            self.logger.warning("Библиотека docxtpl не установлена. "
                                "Часть тестов будет пропущена.")

    def test_01_init_manager(self):
        """ТЕСТ 1: Инициализация менеджера"""
        self.logger.section("1. Инициализация WordExportManager")

        try:
            from Daman_QGIS.managers import WordExportManager

            self.manager = WordExportManager(self.template_dir)
            self.logger.success("WordExportManager создан успешно")

            # Проверяем атрибуты
            self.logger.check(
                hasattr(self.manager, 'template_dir'),
                "Атрибут template_dir существует",
                "Атрибут template_dir отсутствует!"
            )

            self.logger.check(
                str(self.manager.template_dir) == self.template_dir,
                f"template_dir корректен: {self.manager.template_dir}",
                f"template_dir некорректен: {self.manager.template_dir}"
            )

            # Проверяем методы
            methods = ['render', 'render_to_bytes', 'list_templates',
                       'template_exists', 'validate_template', 'clear_cache']
            for method in methods:
                self.logger.check(
                    hasattr(self.manager, method),
                    f"Метод {method}() существует",
                    f"Метод {method}() отсутствует!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка инициализации: {str(e)}")

    def test_02_init_creates_missing_dir(self):
        """ТЕСТ 2: Создание отсутствующей директории"""
        self.logger.section("2. Автоматическое создание директории")

        try:
            from Daman_QGIS.managers import WordExportManager

            new_dir = os.path.join(self.test_dir, "new_templates_dir")
            self.logger.check(
                not os.path.exists(new_dir),
                "Директория не существует до создания менеджера",
                "Директория уже существует!"
            )

            manager = WordExportManager(new_dir)

            self.logger.check(
                os.path.exists(new_dir),
                "Директория создана автоматически",
                "Директория не была создана!"
            )

            self.logger.success("Автоматическое создание директории работает")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_03_list_templates_empty(self):
        """ТЕСТ 3: Список шаблонов (пустая директория)"""
        self.logger.section("3. Список шаблонов (пустая директория)")

        try:
            templates = self.manager.list_templates()

            self.logger.check(
                isinstance(templates, list),
                "list_templates() возвращает список",
                f"Неверный тип: {type(templates)}"
            )

            self.logger.check(
                len(templates) == 0,
                "Список шаблонов пуст для пустой директории",
                f"Список не пуст: {templates}"
            )

            self.logger.success("list_templates() для пустой директории работает")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_04_template_exists(self):
        """ТЕСТ 4: Проверка существования шаблона"""
        self.logger.section("4. Проверка template_exists()")

        try:
            # Несуществующий шаблон
            self.logger.check(
                not self.manager.template_exists("несуществующий.docx"),
                "template_exists() возвращает False для несуществующего",
                "template_exists() некорректно для несуществующего!"
            )

            # Создаем файл (не .docx)
            txt_file = os.path.join(self.template_dir, "test.txt")
            Path(txt_file).touch()

            self.logger.check(
                not self.manager.template_exists("test.txt"),
                "template_exists() возвращает False для .txt файла",
                "template_exists() некорректно для .txt!"
            )

            self.logger.success("template_exists() работает корректно")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_05_get_template_path(self):
        """ТЕСТ 5: Получение пути к шаблону"""
        self.logger.section("5. Получение пути к шаблону")

        try:
            path = self.manager.get_template_path("test.docx")

            self.logger.check(
                isinstance(path, Path),
                "get_template_path() возвращает Path",
                f"Неверный тип: {type(path)}"
            )

            expected = Path(self.template_dir) / "test.docx"
            self.logger.check(
                path == expected,
                f"Путь корректен: {path}",
                f"Путь некорректен: {path} != {expected}"
            )

            # Проверка поддиректории
            subdir_path = self.manager.get_template_path("hlu/test.docx")
            expected_sub = Path(self.template_dir) / "hlu" / "test.docx"
            self.logger.check(
                subdir_path == expected_sub,
                f"Путь с поддиректорией корректен",
                f"Путь с поддиректорией некорректен"
            )

            self.logger.success("get_template_path() работает корректно")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_06_format_area(self):
        """ТЕСТ 6: Форматирование площади"""
        self.logger.section("6. Форматирование площади format_area()")

        try:
            from Daman_QGIS.managers import WordExportManager

            # Стандартный случай
            result = WordExportManager.format_area(0.0231)
            self.logger.check(
                result == "0,0231",
                f"format_area(0.0231) = '{result}'",
                f"Ожидалось '0,0231', получено '{result}'"
            )

            # Разное количество знаков
            result2 = WordExportManager.format_area(1.5, decimals=2)
            self.logger.check(
                result2 == "1,50",
                f"format_area(1.5, decimals=2) = '{result2}'",
                f"Ожидалось '1,50', получено '{result2}'"
            )

            # None значение
            result3 = WordExportManager.format_area(None)
            self.logger.check(
                result3 == "-",
                f"format_area(None) = '{result3}'",
                f"Ожидалось '-', получено '{result3}'"
            )

            # Ноль
            result4 = WordExportManager.format_area(0.0)
            self.logger.check(
                result4 == "0,0000",
                f"format_area(0.0) = '{result4}'",
                f"Ожидалось '0,0000', получено '{result4}'"
            )

            self.logger.success("format_area() работает корректно")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_07_format_area_zapas(self):
        """ТЕСТ 7: Форматирование площади/запаса"""
        self.logger.section("7. Форматирование format_area_zapas()")

        try:
            from Daman_QGIS.managers import WordExportManager

            # Стандартный случай
            result = WordExportManager.format_area_zapas(0.0231, 15)
            self.logger.check(
                result == "0,0231 / 15",
                f"format_area_zapas(0.0231, 15) = '{result}'",
                f"Ожидалось '0,0231 / 15', получено '{result}'"
            )

            # None площадь
            result2 = WordExportManager.format_area_zapas(None, 15)
            self.logger.check(
                result2 == "-",
                f"format_area_zapas(None, 15) = '{result2}'",
                f"Ожидалось '-', получено '{result2}'"
            )

            # Нулевая площадь
            result3 = WordExportManager.format_area_zapas(0, 15)
            self.logger.check(
                result3 == "-",
                f"format_area_zapas(0, 15) = '{result3}'",
                f"Ожидалось '-', получено '{result3}'"
            )

            # None запас
            result4 = WordExportManager.format_area_zapas(1.5, None)
            self.logger.check(
                result4 == "1,5000 / 0",
                f"format_area_zapas(1.5, None) = '{result4}'",
                f"Ожидалось '1,5000 / 0', получено '{result4}'"
            )

            self.logger.success("format_area_zapas() работает корректно")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_08_validate_template_missing(self):
        """ТЕСТ 8: Валидация несуществующего шаблона"""
        self.logger.section("8. Валидация несуществующего шаблона")

        try:
            result = self.manager.validate_template("несуществующий.docx")

            self.logger.check(
                isinstance(result, dict),
                "validate_template() возвращает dict",
                f"Неверный тип: {type(result)}"
            )

            self.logger.check(
                result.get("valid") is False,
                "valid = False для несуществующего шаблона",
                f"valid = {result.get('valid')}"
            )

            self.logger.check(
                result.get("error") is not None,
                f"error содержит описание: {result.get('error')}",
                "error пуст!"
            )

            self.logger.success("validate_template() для несуществующего шаблона работает")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_09_validate_template_not_docx(self):
        """ТЕСТ 9: Валидация не-docx файла"""
        self.logger.section("9. Валидация не-docx файла")

        try:
            # Создаем .txt файл
            txt_file = os.path.join(self.template_dir, "test_validation.txt")
            with open(txt_file, 'w') as f:
                f.write("test content")

            result = self.manager.validate_template("test_validation.txt")

            self.logger.check(
                result.get("valid") is False,
                "valid = False для .txt файла",
                f"valid = {result.get('valid')}"
            )

            self.logger.check(
                "не является .docx" in str(result.get("error", "")).lower()
                or "docx" in str(result.get("error", "")).lower(),
                f"error упоминает .docx: {result.get('error')}",
                f"error не содержит информации о формате: {result.get('error')}"
            )

            self.logger.success("validate_template() для не-docx работает")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_10_render_missing_template(self):
        """ТЕСТ 10: Рендеринг несуществующего шаблона"""
        self.logger.section("10. Рендеринг несуществующего шаблона")

        try:
            output_path = os.path.join(self.test_dir, "output.docx")
            result = self.manager.render(
                "несуществующий.docx",
                {"test": "value"},
                output_path
            )

            self.logger.check(
                result is False,
                "render() возвращает False для несуществующего шаблона",
                f"render() вернул {result}"
            )

            self.logger.check(
                not os.path.exists(output_path),
                "Выходной файл не создан",
                "Выходной файл был создан!"
            )

            self.logger.success("render() корректно обрабатывает отсутствующий шаблон")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_11_clear_cache(self):
        """ТЕСТ 11: Очистка кэша"""
        self.logger.section("11. Очистка кэша шаблонов")

        try:
            # Проверяем, что метод существует и не падает
            self.manager.clear_cache()
            self.logger.success("clear_cache() выполнен без ошибок")

            # Проверяем, что кэш пуст
            self.logger.check(
                len(self.manager._template_cache) == 0,
                "Кэш шаблонов очищен",
                f"Кэш не пуст: {len(self.manager._template_cache)} элементов"
            )

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_12_singleton(self):
        """ТЕСТ 12: Проверка синглтона"""
        self.logger.section("12. Проверка синглтон-паттерна")

        try:
            from Daman_QGIS.managers import registry

            # Сбрасываем синглтон
            registry.reset('M_33')

            # Получаем первый экземпляр
            manager1 = registry.get('M_33')
            self.logger.check(
                manager1 is not None,
                "registry.get('M_33') возвращает экземпляр",
                "registry.get('M_33') вернул None!"
            )

            # Получаем второй экземпляр
            manager2 = registry.get('M_33')
            self.logger.check(
                manager1 is manager2,
                "Синглтон возвращает тот же экземпляр",
                "Синглтон создает новые экземпляры!"
            )

            # Сброс синглтона
            registry.reset('M_33')

            # После сброса - новый экземпляр
            manager3 = registry.get('M_33')
            self.logger.check(
                manager1 is not manager3,
                "После reset создается новый экземпляр",
                "После reset возвращается старый экземпляр!"
            )

            self.logger.success("Синглтон-паттерн работает корректно")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")


def run_tests(iface, logger):
    """Точка входа для запуска тестов"""
    test = TestM33(iface, logger)
    test.run_all_tests()
    return test
