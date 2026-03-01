# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_comprehensive_runner - Комплексное тестирование плагина

НАЗНАЧЕНИЕ:
  Автоматический запуск ВСЕХ тестов плагина (Fsm_4_2_T_*.py) без пропусков.
  Симуляция полного цикла разработки проекта.

ОСОБЕННОСТИ:
  - Автоматическое обнаружение всех тестов (test discovery)
  - Последовательный запуск (избегаем конфликтов между тестами)
  - LOG_LEVEL_ERROR - только ошибки (для уменьшения объёма логов)
  - Сводный отчёт об ошибках по всем тестам

ИСПОЛЬЗОВАНИЕ:
  Вызывается из F_4_2_test.py -> "Комплексный тест"

STRUCTURE:
  /Fsm_4_2_T_comprehensive_runner/
  ├── __init__.py              # Package exports
  ├── conftest.py              # Data classes for test cases
  ├── Fsm_4_2_1_test_logger.py # Test logging infrastructure
  ├── Fsm_4_2_T_comprehensive_runner.py  # This file (main orchestrator)
  ├── Fsm_4_2_T_*.py          # Individual test modules
  └── fixtures/                # Test fixtures
      ├── layer_fixtures.py
      └── project_fixtures.py
"""

import os
import glob
import importlib
import importlib.util
from typing import Callable, List, Dict, Any, Optional

from .Fsm_4_2_1_test_logger import TestLogger
from Daman_QGIS.utils import log_info, log_error
from Daman_QGIS.managers import track_exception

# Import fixtures for cleanup
from .fixtures.project_fixtures import cleanup_test_project


class ComprehensiveTestRunner:
    """
    Фабрикатор всех тестов плагина

    Автоматически находит и запускает все Fsm_4_2_T_*.py модули
    """

    # Исключить из комплексного теста (вспомогательные модули, не тесты)
    EXCLUDED_FILES = {
        'Fsm_4_2_1_test_logger.py',  # Логгер (не матчится паттерном, но для страховки)
        'Fsm_4_2_T_comprehensive_runner.py',  # Сам себя
        'Fsm_4_2_T_4_1.py',  # F_3_cartometry не существует (в разработке)
    }

    # Модули, требующие GUI (пропускаем в автономном режиме)
    GUI_DEPENDENT_MODULES = {
        # Добавить при необходимости
    }

    # Модули, требующие сетевого подключения (могут зависать на timeouts)
    NETWORK_DEPENDENT_MODULES = {
        'Fsm_4_2_T_1_2.py',              # OSM Loader / Overpass API (может зависать на timeouts)
        'Fsm_4_2_T_1_2_2.py',            # OSM Loader unit tests (запрос к 127.0.0.1 в секции 6)
        'Fsm_4_2_T_api.py',              # API тесты (Yandex Cloud)
        'Fsm_4_2_T_network.py',          # Сетевые тесты
        'Fsm_4_2_T_security.py',         # Тесты безопасности API
        'Fsm_4_2_T_telemetry.py',        # Телеметрия (API endpoint)
        'Fsm_4_2_T_dadata.py',           # DaData API (M_39)
        'Fsm_4_2_T_nspd.py',             # NSPD API stability monitoring
    }

    def __init__(self, iface, log_level: int = TestLogger.LOG_LEVEL_ERROR,
                 skip_network_tests: bool = False,
                 progress_callback: Optional[Callable[[int, int, str], None]] = None):
        """
        Инициализация comprehensive runner

        Args:
            iface: QGIS interface
            log_level: Уровень логирования (по умолчанию ERROR - только ошибки)
            skip_network_tests: Пропустить тесты, требующие сетевого подключения (по умолчанию False)
            progress_callback: Callback прогресса (current_index, total_count, test_name)
        """
        self.iface = iface
        self.logger = TestLogger(log_level=log_level)
        self.skip_network_tests = skip_network_tests
        self._progress_callback = progress_callback

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

        # Поиск всех Fsm_4_2_T_*.py файлов в текущей директории
        pattern = os.path.join(test_dir, 'Fsm_4_2_T_*.py')
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
                # Паттерн: Fsm_4_2_T_1_2*.py (все тесты F_1_2)
                if filename.startswith('Fsm_4_2_T_1_2'):
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

    def _cleanup_after_finish(self):
        """
        Очистка после завершения всех тестов

        КРИТИЧНО: Помечает проект как "не изменённый" чтобы QGIS
        не спрашивал о сохранении при закрытии приложения.
        """
        try:
            cleanup_test_project()
            log_info("ComprehensiveRunner: Проект очищен после тестов")
        except Exception as e:
            self.logger.error(f"Ошибка очистки после тестов: {e}")

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
        total = len(test_files)
        for i, test_path in enumerate(test_files):
            test_name = os.path.basename(test_path)

            # Уведомляем UI о текущем тесте
            if self._progress_callback:
                self._progress_callback(i, total, test_name)

            result = self._run_single_test(test_path, test_name)
            self.test_results.append(result)

            # Даём Qt event loop обработать события (предотвращает "Not Responding")
            try:
                from qgis.PyQt.QtWidgets import QApplication
                QApplication.processEvents()
            except Exception:
                pass

        # Финальный callback — все тесты завершены
        if self._progress_callback:
            self._progress_callback(total, total, "")

        # КРИТИЧНО: Очистка после завершения всех тестов
        # Без этого QGIS спросит о сохранении изменений при закрытии
        self._cleanup_after_finish()

        # Итоговый отчёт
        self._generate_summary()

    def _run_single_test(self, test_path: str, test_name: str) -> Dict[str, Any]:
        """
        Запуск одного тестового модуля (тихий режим - вывод только при ошибках)
        """
        # DEFENSIVE: Clear logger state BEFORE each test to ensure clean state
        self.logger.clear()

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

            # Отправляем fail'ы тестов в телеметрию (logger.fail() не бросает исключений)
            if self.logger.failed_count > 0:
                # Собираем детали ошибок для телеметрии
                fail_details = [line for line in self.logger.log_lines
                               if 'FAIL:' in line or 'ERROR:' in line]
                # Отправляем в телеметрию
                try:
                    from Daman_QGIS.managers import registry
                    telemetry_mgr = registry.get('M_32')
                    if telemetry_mgr:
                        telemetry_mgr.track_event(
                            event_type="test_failure",
                            data={
                                "test_module": test_name,
                                "failed_count": self.logger.failed_count,
                                "errors": fail_details[:10]  # Лимит 10 ошибок
                            }
                        )
                except Exception:
                    pass  # Телеметрия не должна ломать тесты

        except Exception as e:
            result['status'] = 'error'
            result['error_message'] = str(e)
            import traceback
            result['errors_detail'] = [traceback.format_exc()]

            # Отправляем ошибку в телеметрию (обработанные исключения не попадают в sys.excepthook)
            track_exception(f"Fsm_4_2_T:{test_name}", e, {"test_module": test_name})

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

        log_info(
            f"ComprehensiveRunner: Итог - passed={self.total_passed}, "
            f"failed={self.total_failed}, warnings={self.total_warnings}, "
            f"error_tests={error_tests}, modules={total_tests}"
        )

        if self.total_failed == 0 and error_tests == 0:
            # Без ошибок — одна строка
            self.logger.log_lines.append("ВСЕ ТЕСТЫ ПРОЙДЕНЫ, ВСЕ OK")
        else:
            # Только ошибки — детальный список
            self.logger.log_lines.append("ОШИБКИ:")

            for result in self.test_results:
                if result['status'] in ['failed', 'error']:
                    module_display = result['name'].replace('Fsm_4_2_T_', '').replace('.py', '')
                    self.logger.log_lines.append(f"  [{module_display}]")
                    log_info(f"ComprehensiveRunner: FAIL module: {module_display}")

                    if result['error_message']:
                        self.logger.log_lines.append(f"    {result['error_message']}")

                    if result['errors_detail']:
                        for detail in result['errors_detail'][:10]:
                            self.logger.log_lines.append(f"    {detail}")

                    if not result['error_message'] and not result['errors_detail']:
                        self.logger.log_lines.append(f"    (failed_count={result['failed']}, без деталей)")

    def get_results(self) -> List[Dict]:
        """Получить результаты всех тестов"""
        return self.test_results
