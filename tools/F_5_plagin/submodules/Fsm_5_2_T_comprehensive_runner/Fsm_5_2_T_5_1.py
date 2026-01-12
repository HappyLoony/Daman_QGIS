# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_5_1 - Тест функции F_5_1_Проверка зависимостей
Проверка установки библиотек, шрифтов, сертификатов
"""

import sys


class TestF51:
    """Тесты для функции F_5_1_CheckDependencies"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.module = None

    def run_all_tests(self):
        """Запуск всех тестов F_5_1"""
        self.logger.section("ТЕСТ F_5_1: Проверка зависимостей")

        try:
            self.test_01_init_module()
            self.test_02_check_methods()
            self.test_03_builtin_dependencies()
            self.test_04_external_dependencies()
            self.test_05_python_executable()
            self.test_06_quick_check()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов F_5_1: {str(e)}")

        self.logger.summary()

    def test_01_init_module(self):
        """ТЕСТ 1: Инициализация модуля F_5_1"""
        self.logger.section("1. Инициализация F_5_1_CheckDependencies")

        try:
            from Daman_QGIS.tools.F_5_plagin.F_5_1_check_dependencies import F_5_1_CheckDependencies

            self.module = F_5_1_CheckDependencies(self.iface)
            self.logger.success("Модуль F_5_1_CheckDependencies загружен")

            # Проверяем наличие свойства name
            if hasattr(self.module, 'name'):
                name = self.module.name
                self.logger.check(
                    "5_1" in name or "зависимост" in name.lower(),
                    f"Имя модуля корректное: '{name}'",
                    f"Имя модуля некорректное: '{name}'"
                )

        except Exception as e:
            self.logger.error(f"Ошибка инициализации: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
            self.module = None

    def test_02_check_methods(self):
        """ТЕСТ 2: Проверка наличия методов"""
        self.logger.section("2. Проверка методов модуля")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            # Проверяем методы
            self.logger.check(
                hasattr(self.module, 'run'),
                "Метод run существует",
                "Метод run отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, 'quick_check'),
                "Метод quick_check существует",
                "Метод quick_check отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, 'get_python_executable'),
                "Метод get_python_executable существует",
                "Метод get_python_executable отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, 'get_external_dependencies'),
                "Метод get_external_dependencies существует",
                "Метод get_external_dependencies отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, 'get_install_paths'),
                "Метод get_install_paths существует",
                "Метод get_install_paths отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, 'create_dialog'),
                "Метод create_dialog существует",
                "Метод create_dialog отсутствует!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка проверки методов: {str(e)}")

    def test_03_builtin_dependencies(self):
        """ТЕСТ 3: Проверка встроенных зависимостей"""
        self.logger.section("3. Проверка BUILTIN_DEPENDENCIES")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            # Проверяем наличие словаря
            self.logger.check(
                hasattr(self.module, 'BUILTIN_DEPENDENCIES'),
                "BUILTIN_DEPENDENCIES существует",
                "BUILTIN_DEPENDENCIES отсутствует!"
            )

            if hasattr(self.module, 'BUILTIN_DEPENDENCIES'):
                builtin = self.module.BUILTIN_DEPENDENCIES
                self.logger.info(f"Встроенных зависимостей: {len(builtin)}")

                for dep_name in builtin:
                    self.logger.data(f"  -", dep_name)

        except Exception as e:
            self.logger.error(f"Ошибка проверки BUILTIN_DEPENDENCIES: {str(e)}")

    def test_04_external_dependencies(self):
        """ТЕСТ 4: Проверка внешних зависимостей"""
        self.logger.section("4. Проверка внешних зависимостей (requirements.txt)")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            external = self.module.get_external_dependencies()
            self.logger.info(f"Внешних зависимостей: {len(external)}")

            # Проверяем ключевые библиотеки
            expected_libs = ['ezdxf', 'xlsxwriter', 'openpyxl', 'requests', 'lxml']

            for lib in expected_libs:
                if lib in external:
                    self.logger.success(f"{lib}: {external[lib]}")
                else:
                    self.logger.warning(f"{lib} не найден в requirements.txt")

        except Exception as e:
            self.logger.error(f"Ошибка проверки внешних зависимостей: {str(e)}")

    def test_05_python_executable(self):
        """ТЕСТ 5: Проверка определения Python"""
        self.logger.section("5. Проверка get_python_executable")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            python_exe = self.module.get_python_executable()
            self.logger.info(f"Python executable: {python_exe}")

            # Проверяем что путь существует
            import os
            self.logger.check(
                os.path.exists(python_exe),
                "Python executable существует",
                f"Python executable не найден: {python_exe}"
            )

            # Проверяем что это python
            self.logger.check(
                'python' in python_exe.lower(),
                "Путь содержит 'python'",
                f"Неожиданный путь: {python_exe}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка проверки Python executable: {str(e)}")

    def test_06_quick_check(self):
        """ТЕСТ 6: Быстрая проверка зависимостей"""
        self.logger.section("6. Быстрая проверка quick_check()")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            result = self.module.quick_check()

            if result:
                self.logger.success("quick_check(): все зависимости установлены")
            else:
                self.logger.warning("quick_check(): некоторые зависимости отсутствуют")

        except Exception as e:
            self.logger.error(f"Ошибка quick_check: {str(e)}")
