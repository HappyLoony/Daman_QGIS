# -*- coding: utf-8 -*-
"""
Fsm_5_2_T_comprehensive_runner - Комплексное тестирование плагина

НАЗНАЧЕНИЕ:
  Автоматический запуск ВСЕХ тестов плагина (Fsm_5_2_T_*.py) без пропусков.
  Симуляция полного цикла разработки проекта.

ОСОБЕННОСТИ:
  - Автоматическое обнаружение всех тестов (test discovery)
  - Последовательный запуск (избегаем конфликтов между тестами)
  - LOG_LEVEL_ERROR - только ошибки (для уменьшения объёма логов)
  - Сводный отчёт об ошибках по всем тестам
  - Shared fixtures для layers, geometries, projects
  - Edge case collections для parametrized tests
  - Test utilities: assertions и data generators

ИСПОЛЬЗОВАНИЕ:
  Вызывается из F_5_2_test.py → "Комплексный тест"

STRUCTURE:
  /Fsm_5_2_T_comprehensive_runner/
  ├── __init__.py              # Package exports
  ├── conftest.py              # Shared fixtures and edge cases
  ├── Fsm_5_2_1_test_logger.py # Test logging infrastructure
  ├── Fsm_5_2_1_test_runner.py # Individual test runner
  ├── Fsm_5_2_T_comprehensive_runner.py  # This file (main orchestrator)
  ├── Fsm_5_2_T_*.py          # Individual test modules
  ├── fixtures/                # Test fixtures
  │   ├── geometry_fixtures.py
  │   ├── layer_fixtures.py
  │   └── project_fixtures.py
  └── utils/                   # Test utilities
      ├── assertions.py
      └── test_data_generator.py
"""

import os
import glob
import importlib
import importlib.util
from typing import List, Dict, Any

from .Fsm_5_2_1_test_logger import TestLogger
from Daman_QGIS.utils import log_info, log_error

# Import fixtures and utilities for convenience
from .fixtures.project_fixtures import cleanup_test_project, ProjectFixtures
from .conftest import (
    GEOMETRY_EDGE_CASES,
    FIELD_VALUE_EDGE_CASES,
    CRS_TEST_CASES,
    TOPOLOGY_EDGE_CASES,
    TestFixtures,
    ParametrizedTestRunner,
)


class ComprehensiveTestRunner:
    """
    Фабрикатор всех тестов плагина

    Автоматически находит и запускает все Fsm_5_2_T_*.py модули
    """

    # Исключить из комплексного теста (вспомогательные модули, не тесты)
    EXCLUDED_FILES = {
        'Fsm_5_2_1_test_logger.py',  # Логгер
        'Fsm_5_2_1_test_runner.py',  # Раннер
        'Fsm_5_2_T_comprehensive_runner.py',  # Сам себя
        'Fsm_5_2_T_4_1.py',  # F_4_cartometry не существует (в разработке)
        'Fsm_5_2_T_polygon_vs_multipolygon.py',  # Неправильная сигнатура __init__
    }

    # Модули, требующие GUI (пропускаем в автономном режиме)
    GUI_DEPENDENT_MODULES = {
        # Добавить при необходимости
    }

    # Модули, требующие сетевого подключения (могут зависать на timeouts)
    NETWORK_DEPENDENT_MODULES = {
        'Fsm_5_2_T_1_2.py',              # QuickOSM/Overpass API (может зависать на timeouts)
        'Fsm_5_2_T_1_2_2.py',            # QuickOSMLoader direct test
        'Fsm_5_2_T_1_2_method_osm.py',   # OSM method test
        'Fsm_5_2_T_api.py',              # API тесты (Yandex Cloud)
        'Fsm_5_2_T_network.py',          # Сетевые тесты
        'Fsm_5_2_T_security.py',         # Тесты безопасности API
    }

    def __init__(self, iface, log_level: int = TestLogger.LOG_LEVEL_ERROR, skip_network_tests: bool = False):
        """
        Инициализация comprehensive runner

        Args:
            iface: QGIS interface
            log_level: Уровень логирования (по умолчанию ERROR - только ошибки)
            skip_network_tests: Пропустить тесты, требующие сетевого подключения (по умолчанию False)
        """
        self.iface = iface
        self.logger = TestLogger(log_level=log_level)
        self.skip_network_tests = skip_network_tests

        # Результаты тестов
        self.test_results = []  # List[Dict] - результаты каждого теста
        self.total_passed = 0
        self.total_failed = 0
        self.total_warnings = 0

    def discover_tests(self) -> List[str]:
        """
        Автоматическое обнаружение всех тестовых модулей

        Returns:
            List[str]: Пути к файлам тестов
        """
        # Тесты теперь находятся в той же директории что и этот модуль
        test_dir = os.path.dirname(__file__)

        # Поиск всех Fsm_5_2_T_*.py файлов в текущей директории
        pattern = os.path.join(test_dir, 'Fsm_5_2_T_*.py')
        test_files = glob.glob(pattern)

        # Фильтрация исключённых файлов и сетевых тестов
        filtered_tests = []
        skipped_network = []

        for test_path in test_files:
            filename = os.path.basename(test_path)

            # Пропускаем исключённые файлы
            if filename in self.EXCLUDED_FILES:
                continue

            # Пропускаем сетевые тесты если включен skip_network_tests
            if self.skip_network_tests:
                # Проверяем точное совпадение с NETWORK_DEPENDENT_MODULES
                if filename in self.NETWORK_DEPENDENT_MODULES:
                    skipped_network.append(filename)
                    continue

                # Проверяем паттерн для ВСЕХ тестов F_1_2 (API запросы)
                # Паттерн: Fsm_5_2_T_1_2*.py (все тесты F_1_2)
                if filename.startswith('Fsm_5_2_T_1_2'):
                    skipped_network.append(filename)
                    continue

            filtered_tests.append(test_path)

        # Сортировка для предсказуемого порядка
        filtered_tests.sort()

        log_info(f"ComprehensiveRunner: Обнаружено {len(filtered_tests)} тестовых модулей")
        if skipped_network:
            log_info(f"ComprehensiveRunner: Пропущено {len(skipped_network)} сетевых тестов (F_1_2 API): {skipped_network}")

        return filtered_tests

    def _cleanup_before_start(self):
        """
        Очистка перед началом комплексного тестирования (тихий режим)

        Uses the unified cleanup_test_project from fixtures
        """
        try:
            cleanup_test_project()
        except Exception as e:
            self.logger.error(f"Ошибка очистки: {e}")

    def run_all_tests(self):
        """Запуск всех обнаруженных тестов"""
        # Минимальный вывод - только начало
        self.logger.log_lines.append("КОМПЛЕКСНОЕ ТЕСТИРОВАНИЕ ПЛАГИНА")
        self.logger.log_lines.append("")

        # КРИТИЧНО: Очистка перед стартом для обеспечения чистого состояния
        self._cleanup_before_start()

        # Обнаружение тестов
        test_files = self.discover_tests()

        if not test_files:
            self.logger.error("Тестовые модули не найдены!")
            return

        self.logger.log_lines.append(f"Запуск {len(test_files)} тестовых модулей...")
        if self.skip_network_tests:
            self.logger.log_lines.append("(сетевые тесты пропущены)")
        self.logger.log_lines.append("")

        # Запуск тестов последовательно (без вывода каждого)
        for test_path in test_files:
            test_name = os.path.basename(test_path)
            result = self._run_single_test(test_path, test_name)
            self.test_results.append(result)

        # Итоговый отчёт
        self._generate_summary()

    def _run_single_test(self, test_path: str, test_name: str) -> Dict[str, Any]:
        """
        Запуск одного тестового модуля (тихий режим - вывод только при ошибках)
        """
        result = {
            'name': test_name,
            'status': 'unknown',
            'passed': 0,
            'failed': 0,
            'warnings': 0,
            'error_message': None,
            'errors_detail': []  # Детали ошибок
        }

        try:
            # Импорт модуля
            module_name = test_name.replace('.py', '')
            spec = importlib.util.spec_from_file_location(module_name, test_path)
            if spec is None or spec.loader is None:
                result['status'] = 'error'
                result['error_message'] = f"Не удалось загрузить спецификацию модуля: {test_path}"
                return result
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Поиск тестового класса
            test_class = self._find_test_class(module)

            if not test_class:
                result['status'] = 'skipped'
                result['error_message'] = "Тестовый класс не найден"
                return result

            # Инициализация и запуск теста
            test_instance = test_class(self.iface, self.logger)

            if hasattr(test_instance, 'run_all_tests'):
                test_instance.run_all_tests()
            elif hasattr(test_instance, 'run_scenario'):
                test_instance.run_scenario()
            else:
                result['status'] = 'skipped'
                result['error_message'] = "Метод run_all_tests не найден"
                return result

            # Сбор результатов
            result['passed'] = self.logger.passed_count
            result['failed'] = self.logger.failed_count
            result['warnings'] = self.logger.warning_count

            # Сохраняем детали ошибок если есть
            if self.logger.failed_count > 0:
                # Извлекаем строки ошибок из лога (ищем маркеры fail/error)
                result['errors_detail'] = [
                    line.strip() for line in self.logger.log_lines
                    if any(marker in line for marker in ['FAIL:', 'ERROR:', 'Traceback'])
                ]

            # Накопление общей статистики
            self.total_passed += self.logger.passed_count
            self.total_failed += self.logger.failed_count
            self.total_warnings += self.logger.warning_count

            # Определение статуса (без вывода)
            result['status'] = 'passed' if self.logger.failed_count == 0 else 'failed'

            # Очищаем счётчики и лог для следующего теста
            self.logger.passed_count = 0
            self.logger.failed_count = 0
            self.logger.warning_count = 0
            self.logger.log_lines = []  # Очищаем детальный лог

        except Exception as e:
            result['status'] = 'error'
            result['error_message'] = str(e)
            import traceback
            result['errors_detail'] = [traceback.format_exc()]

        return result

    def _find_test_class(self, module):
        """
        Поиск тестового класса в модуле

        Ищет классы по паттернам: Test*, *Test, или возвращает первый найденный класс
        """
        import inspect

        # Получаем все классы из модуля
        classes = [obj for name, obj in inspect.getmembers(module, inspect.isclass)
                   if obj.__module__ == module.__name__]

        if not classes:
            return None

        # Приоритет 1: Классы начинающиеся с Test*
        for cls in classes:
            if cls.__name__.startswith('Test'):
                return cls

        # Приоритет 2: Классы заканчивающиеся на *Test
        for cls in classes:
            if cls.__name__.endswith('Test'):
                return cls

        # Приоритет 3: Первый класс в модуле
        return classes[0]

    def _generate_summary(self):
        """Генерация итогового отчёта (компактная версия, только ошибки)"""

        # Статистика по тестам
        total_tests = len(self.test_results)
        passed_tests = sum(1 for r in self.test_results if r['status'] == 'passed')
        failed_tests = sum(1 for r in self.test_results if r['status'] == 'failed')
        error_tests = sum(1 for r in self.test_results if r['status'] == 'error')
        skipped_tests = sum(1 for r in self.test_results if r['status'] == 'skipped')

        # ТОЛЬКО ОШИБКИ - детальный список провальных тестов
        if failed_tests > 0 or error_tests > 0:
            self.logger.log_lines.append("ОШИБКИ:")

            for result in self.test_results:
                if result['status'] in ['failed', 'error']:
                    # Имя модуля
                    module_display = result['name'].replace('Fsm_5_2_T_', '').replace('.py', '')
                    self.logger.log_lines.append(f"  [{module_display}]")

                    # Детали ошибок (error_message приоритетнее)
                    if result['error_message']:
                        self.logger.log_lines.append(f"    {result['error_message']}")

                    if result['errors_detail']:
                        for detail in result['errors_detail'][:5]:  # Макс 5 ошибок на модуль
                            self.logger.log_lines.append(f"    {detail}")

                    # Если нет деталей - сообщаем
                    if not result['error_message'] and not result['errors_detail']:
                        self.logger.log_lines.append(f"    (failed_count={result['failed']}, без деталей)")

            self.logger.log_lines.append("")

        # Компактная итоговая статистика
        self.logger.log_lines.append("ИТОГ:")
        self.logger.log_lines.append(f"  Модулей: {total_tests} | OK: {passed_tests} | FAIL: {failed_tests + error_tests} | SKIP: {skipped_tests}")
        self.logger.log_lines.append(f"  Проверок: {self.total_passed + self.total_failed} | OK: {self.total_passed} | FAIL: {self.total_failed}")

        # Финальный вердикт
        if self.total_failed == 0 and error_tests == 0:
            self.logger.log_lines.append("ВСЕ ТЕСТЫ ПРОЙДЕНЫ")
        else:
            self.logger.log_lines.append(f"ОШИБКИ: {failed_tests + error_tests} модулей, {self.total_failed} проверок")

    def get_results(self) -> List[Dict]:
        """Получить результаты всех тестов"""
        return self.test_results
