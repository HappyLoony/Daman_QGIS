# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_pyright - Тест статической типизации (pyright/pylance)

Проверяет:
1. Наличие qgis-stubs и PyQt5-stubs
2. Наличие pyrightconfig.json
3. Запуск pyright и подсчёт ошибок типизации
4. Отслеживание прогресса исправления ошибок

ТРЕБОВАНИЯ:
- qgis-stubs (устанавливается через F_5_1)
- PyQt5-stubs (устанавливается автоматически с qgis-stubs)
- pyright (npm install -g pyright) или npx pyright
"""

import os
import subprocess
import json
from typing import Optional, Dict, Any, List


class TestPyright:
    """Тесты статической типизации с pyright"""

    def __init__(self, iface: Any, logger: Any) -> None:
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.plugin_root = self._get_plugin_root()
        self.pyright_config: Optional[Dict[str, Any]] = None
        self.pyright_output: Optional[Dict[str, Any]] = None

    def _get_plugin_root(self) -> str:
        """Получить корневую папку плагина"""
        # Путь: Fsm_5_2_T_pyright.py -> Fsm_5_2_T_comprehensive_runner -> submodules -> F_5_plagin -> tools -> Daman_QGIS
        current = os.path.dirname(__file__)
        for _ in range(4):
            current = os.path.dirname(current)
        return current

    def run_all_tests(self) -> None:
        """Запуск всех тестов pyright"""
        self.logger.section("ТЕСТ PYRIGHT: Статическая типизация")

        try:
            self.test_01_check_qgis_stubs()
            self.test_02_check_pyrightconfig()
            self.test_03_run_pyright()
            self.test_04_analyze_errors()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов pyright: {str(e)}")

        self.logger.summary()

    def test_01_check_qgis_stubs(self) -> None:
        """ТЕСТ 1: Проверка установки qgis-stubs и PyQt5-stubs"""
        self.logger.section("1. Проверка type stubs")

        try:
            from importlib.metadata import version as get_version, PackageNotFoundError
            from packaging.version import parse as parse_version

            # Проверяем qgis-stubs
            try:
                stubs_version = get_version('qgis-stubs')
                self.logger.success(f"qgis-stubs установлен: v{stubs_version}")

                # Проверяем минимальную версию
                if parse_version(stubs_version) >= parse_version('0.2.0'):
                    self.logger.success("Версия qgis-stubs >= 0.2.0")
                else:
                    self.logger.warning("Рекомендуется обновить qgis-stubs до 0.2.0+")

            except PackageNotFoundError:
                self.logger.warning("qgis-stubs не установлен (рекомендуется для type checking)")
                self.logger.info("Установка: pip install qgis-stubs (или через F_5_1)")

            # Проверяем PyQt5-stubs
            try:
                pyqt5_stubs_version = get_version('PyQt5-stubs')
                self.logger.success(f"PyQt5-stubs установлен: v{pyqt5_stubs_version}")

                # Проверяем минимальную версию
                if parse_version(pyqt5_stubs_version) >= parse_version('5.15.0'):
                    self.logger.success("Версия PyQt5-stubs >= 5.15.0")
                else:
                    self.logger.warning("Рекомендуется обновить PyQt5-stubs до 5.15.0+")

            except PackageNotFoundError:
                self.logger.warning("PyQt5-stubs не установлен (устанавливается с qgis-stubs)")
                self.logger.info("Установка: pip install PyQt5-stubs")

        except ImportError:
            self.logger.warning("importlib.metadata или packaging недоступны")

    def test_02_check_pyrightconfig(self) -> None:
        """ТЕСТ 2: Проверка pyrightconfig.json"""
        self.logger.section("2. Проверка pyrightconfig.json")

        config_path = os.path.join(self.plugin_root, 'pyrightconfig.json')

        if not os.path.exists(config_path):
            self.logger.warning("pyrightconfig.json не найден")
            self.logger.info(f"Ожидаемый путь: {config_path}")
            return

        self.logger.success("pyrightconfig.json существует")

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self.pyright_config = json.load(f)

            # Проверяем ключевые настройки
            if 'typeCheckingMode' in self.pyright_config:
                mode = self.pyright_config['typeCheckingMode']
                self.logger.success(f"typeCheckingMode: {mode}")
            else:
                self.logger.info("typeCheckingMode не указан (используется default)")

            if 'pythonVersion' in self.pyright_config:
                py_ver = self.pyright_config['pythonVersion']
                self.logger.success(f"pythonVersion: {py_ver}")

            if 'stubPath' in self.pyright_config:
                self.logger.success(f"stubPath: {self.pyright_config['stubPath']}")

            if 'useLibraryCodeForTypes' in self.pyright_config:
                self.logger.success(f"useLibraryCodeForTypes: {self.pyright_config['useLibraryCodeForTypes']}")

            # Проверяем exclude
            if 'exclude' in self.pyright_config:
                excluded = len(self.pyright_config['exclude'])
                self.logger.info(f"Исключений в exclude: {excluded}")

        except json.JSONDecodeError as e:
            self.logger.fail(f"Ошибка парсинга pyrightconfig.json: {e}")
        except Exception as e:
            self.logger.error(f"Ошибка чтения pyrightconfig.json: {e}")

    def test_03_run_pyright(self) -> None:
        """ТЕСТ 3: Запуск pyright"""
        self.logger.section("3. Запуск pyright")

        # Пробуем разные способы запуска
        pyright_commands = [
            ['npx', 'pyright', '--outputjson'],
            ['pyright', '--outputjson'],
        ]

        for cmd in pyright_commands:
            try:
                self.logger.info(f"Попытка: {' '.join(cmd)}")

                result = subprocess.run(
                    cmd,
                    cwd=self.plugin_root,
                    capture_output=True,
                    text=True,
                    timeout=120,  # 2 минуты timeout
                    shell=(os.name == 'nt')  # Windows требует shell=True
                )

                # pyright возвращает не-0 код при наличии ошибок
                if result.stdout:
                    try:
                        self.pyright_output = json.loads(result.stdout)
                        self.logger.success(f"pyright выполнен успешно")
                        return
                    except json.JSONDecodeError:
                        # Возможно stdout содержит текст, а не JSON
                        self.logger.info("Вывод pyright не в JSON формате")
                        # Пробуем найти количество ошибок в тексте
                        if 'error' in result.stdout.lower():
                            self.logger.warning("pyright нашёл ошибки (см. детали ниже)")
                            # Сохраняем raw output для анализа
                            self.pyright_output = {'raw': result.stdout, 'raw_stderr': result.stderr}
                            return

                if result.stderr:
                    self.logger.info(f"stderr: {result.stderr[:200]}")

            except FileNotFoundError:
                self.logger.info(f"{cmd[0]} не найден")
                continue
            except subprocess.TimeoutExpired:
                self.logger.warning(f"Timeout при запуске {cmd[0]}")
                continue
            except Exception as e:
                self.logger.info(f"Ошибка {cmd[0]}: {str(e)}")
                continue

        # Если ни один способ не сработал
        self.logger.warning("pyright не найден или не удалось запустить")
        self.logger.info("Установка: npm install -g pyright")

    def test_04_analyze_errors(self) -> None:
        """ТЕСТ 4: Анализ ошибок pyright"""
        self.logger.section("4. Анализ ошибок типизации")

        if not self.pyright_output:
            self.logger.info("pyright не был запущен, пропускаем анализ")
            return

        # Обработка JSON вывода
        if 'generalDiagnostics' in self.pyright_output:
            diagnostics = self.pyright_output.get('generalDiagnostics', [])
            summary = self.pyright_output.get('summary', {})

            error_count = summary.get('errorCount', 0)
            warning_count = summary.get('warningCount', 0)
            info_count = summary.get('informationCount', 0)

            self.logger.info(f"Ошибок: {error_count}")
            self.logger.info(f"Предупреждений: {warning_count}")
            self.logger.info(f"Информационных: {info_count}")

            # Проверяем пороги
            if error_count == 0:
                self.logger.success("Нет ошибок типизации")
            elif error_count <= 10:
                self.logger.success(f"Мало ошибок типизации: {error_count}")
            elif error_count <= 50:
                self.logger.warning(f"Средний уровень ошибок: {error_count}")
            else:
                self.logger.warning(f"Много ошибок типизации: {error_count}")

            # Показываем первые 5 ошибок для контекста
            errors_shown = 0
            for diag in diagnostics:
                if diag.get('severity') == 1 and errors_shown < 5:  # 1 = error
                    file_path = diag.get('file', 'unknown')
                    line = diag.get('range', {}).get('start', {}).get('line', 0)
                    message = diag.get('message', 'no message')

                    # Сокращаем путь
                    short_path = os.path.basename(file_path)
                    self.logger.info(f"  {short_path}:{line}: {message[:80]}")
                    errors_shown += 1

            if error_count > 5:
                self.logger.info(f"  ... и ещё {error_count - 5} ошибок")

        # Обработка raw вывода (если JSON не парсился)
        elif 'raw' in self.pyright_output:
            raw = self.pyright_output['raw']
            # Пытаемся найти статистику в тексте
            import re
            match = re.search(r'(\d+)\s+error', raw)
            if match:
                error_count = int(match.group(1))
                if error_count == 0:
                    self.logger.success("Нет ошибок типизации")
                else:
                    self.logger.warning(f"Ошибок типизации: {error_count}")
            else:
                self.logger.info("Не удалось определить количество ошибок")

        else:
            self.logger.info("Неизвестный формат вывода pyright")
