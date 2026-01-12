# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_1_1 - Логгер тестов
Форматированный вывод результатов тестирования

Принцип: минимальный вывод
- Успехи НЕ выводятся (только счётчик в итогах)
- Ошибки и предупреждения выводятся с деталями
- Секции НЕ выводятся (только для внутренней группировки)
"""

from typing import List


class TestLogger:
    """Логгер для форматированного вывода тестов"""

    # Уровни логирования
    LOG_LEVEL_ALL = 0       # Все сообщения (info, warning, error)
    LOG_LEVEL_WARNING = 1   # Только warning + error (без info)
    LOG_LEVEL_ERROR = 2     # Только error (только ошибки)

    def __init__(self, log_level: int = LOG_LEVEL_ALL):
        """
        Инициализация логгера

        Args:
            log_level: Уровень логирования (0=все, 1=warning+, 2=только ошибки)
        """
        self.log_lines: List[str] = []
        self.log_level = log_level
        self.passed_count = 0
        self.failed_count = 0
        self.warning_count = 0
        self._current_section = ""  # Для контекста ошибок

    def clear(self):
        """Очистить лог (сохраняя log_level)"""
        self.log_lines = []
        self.passed_count = 0
        self.failed_count = 0
        self.warning_count = 0
        self._current_section = ""

    def set_log_level(self, log_level: int):
        """
        Установить уровень логирования

        Args:
            log_level: 0 (ALL), 1 (WARNING+), 2 (ERROR only)
        """
        self.log_level = log_level

    def section(self, title: str):
        """Запомнить секцию (НЕ выводит ничего, только для контекста ошибок)"""
        self._current_section = title

    def success(self, message: str):
        """Успешная проверка (НИКОГДА не выводится, только счётчик)"""
        self.passed_count += 1
        # Не добавляем в log_lines - успехи не выводятся

    def fail(self, message: str):
        """Провальная проверка (всегда показывается с контекстом секции)"""
        context = f"[{self._current_section}] " if self._current_section else ""
        self.log_lines.append(f"  FAIL: {context}{message}")
        self.failed_count += 1

    def warning(self, message: str):
        """Предупреждение (показывается при LOG_LEVEL_WARNING и LOG_LEVEL_ALL)"""
        self.warning_count += 1
        if self.log_level <= self.LOG_LEVEL_WARNING:
            context = f"[{self._current_section}] " if self._current_section else ""
            self.log_lines.append(f"  WARN: {context}{message}")

    def info(self, message: str):
        """Информационное сообщение (показывается только при LOG_LEVEL_ALL)"""
        if self.log_level == self.LOG_LEVEL_ALL:
            self.log_lines.append(f"  INFO: {message}")

    def error(self, message: str):
        """Критическая ошибка (всегда показывается)"""
        context = f"[{self._current_section}] " if self._current_section else ""
        self.log_lines.append(f"  ERROR: {context}{message}")
        self.failed_count += 1

    def data(self, key: str, value: str):
        """Вывод данных (только при ошибках, добавляется к контексту)"""
        self.log_lines.append(f"    {key}: {value}")

    def summary(self):
        """Итоговая сводка (компактная)"""
        self.log_lines.append("")
        self.log_lines.append("РЕЗУЛЬТАТ:")
        self.log_lines.append(f"  OK: {self.passed_count} | FAIL: {self.failed_count} | WARN: {self.warning_count}")

        if self.failed_count == 0:
            self.log_lines.append("  ВСЕ ТЕСТЫ ПРОЙДЕНЫ")
        else:
            self.log_lines.append(f"  ОБНАРУЖЕНЫ ОШИБКИ: {self.failed_count}")

    def get_log(self) -> List[str]:
        """Получить все строки лога"""
        return self.log_lines

    def check(self, condition: bool, success_msg: str, fail_msg: str):
        """Проверка условия с автоматическим логированием"""
        if condition:
            self.success(success_msg)
        else:
            self.fail(fail_msg)
