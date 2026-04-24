# -*- coding: utf-8 -*-
"""
Fsm_4_1_16_BackgroundInstallTask - Фоновая установка зависимостей при первом запуске.

Запускает PipInstaller.install_all() в background-потоке через QgsTask (M_17),
прокидывает прогресс в сигнал progress_updated (MessageBar).

Сценарий:
- Первый запуск после установки плагина: vendored wheels лежат в
  %APPDATA%/QGIS/.../python/wheels/, но dependencies/ пуст.
- pip install из локального кэша занимает 5-10 секунд.
- Во время установки пользователь видит QgsMessageBar с прогресс-баром.
- По завершении: флаг plugin.deps_ready = True.

Безопасность для main thread:
- execute() выполняется в worker thread, не трогает GUI напрямую.
- Прогресс эмитится через signal progress_updated (thread-safe).
- Callbacks on_completed/on_failed выполняются в main thread (через M_17).
"""

from typing import Dict, List, Optional

from Daman_QGIS.managers import BaseAsyncTask
from Daman_QGIS.utils import log_info, log_error, log_warning

from .Fsm_4_1_4_pip_installer import PipInstaller


class BackgroundInstallTask(BaseAsyncTask):
    """
    Фоновая задача установки Python-зависимостей через pip.

    Запускается при первом старте плагина если quick_check вернул False.
    Progress reporting через BaseAsyncTask.report_progress() -> MessageBar.

    Result (dict):
        {
            'success': bool,           # True если ни одной ошибки
            'installed': List[str],    # Список успешно установленных пакетов
            'errors': List[str],       # Список ошибок
            'needs_restart': bool,     # True если есть .old файлы (заблокированные)
            'total': int,              # Всего пакетов пытались установить
        }
    """

    MODULE_ID = "Fsm_4_1_16"

    def __init__(self, packages: Dict[str, Dict]):
        """
        Инициализация задачи.

        Args:
            packages: Словарь пакетов для установки (из DependencyChecker)
                     Формат: {имя: {install_cmd, min_version, ...}}
        """
        super().__init__("Установка зависимостей Daman")
        self.packages = packages
        self._completed_count = 0
        self._total_count = len(packages)

    def _emit_progress(self, message: str) -> None:
        """
        Callback для PipInstaller.progress_callback.

        Вычисляет процент на основе кол-ва успешно установленных пакетов
        и пробрасывает сообщение в MessageBar через signal.

        Args:
            message: Текстовое сообщение от PipInstaller
        """
        # Маркер завершения установки пакета — строка вида "OK <pkg> установлен"
        if message.startswith("OK ") and "установлен" in message:
            self._completed_count += 1

        if self._total_count > 0:
            percent = int(self._completed_count / self._total_count * 100)
        else:
            percent = 0

        # Укорачиваем сообщение для MessageBar (подробности уже в логе)
        short_msg = message
        if len(short_msg) > 80:
            short_msg = short_msg[:77] + "..."

        # Сообщение для пользователя — какой пакет сейчас ставится
        display_msg = (
            f"пакет {self._completed_count + 1} из {self._total_count}: {short_msg}"
        )
        self.report_progress(percent, display_msg)

        # Полное сообщение в лог (для последующей диагностики)
        log_info(f"{self.MODULE_ID}: {message}")

    def execute(self) -> Dict:
        """
        Основная логика — установка пакетов через PipInstaller.

        Выполняется в background thread QgsTask.
        НЕ трогает GUI напрямую — только report_progress (thread-safe signal).

        Returns:
            dict: Результат установки (см. docstring класса)
        """
        log_info(
            f"{self.MODULE_ID}: Фоновая установка {self._total_count} пакетов"
        )

        if self._total_count == 0:
            return {
                'success': True,
                'installed': [],
                'errors': [],
                'needs_restart': False,
                'total': 0,
            }

        self.report_progress(0, f"Подготовка установки ({self._total_count} пакетов)")

        # Проверка отмены перед стартом
        if self.is_cancelled():
            return {
                'success': False,
                'installed': [],
                'errors': ['Отменено пользователем'],
                'needs_restart': False,
                'total': self._total_count,
            }

        # Создаём инсталлер с колбэком прогресса
        installer = PipInstaller(
            self.packages,
            progress_callback=self._emit_progress,
        )

        installed: List[str] = []
        errors: List[str] = []

        # install_all делает bootstrap pip + цикл по пакетам.
        # PipInstaller уже логирует через log_info, здесь мы дублируем в signal.
        try:
            errors = installer.install_all()

            # Определяем какие пакеты успешно установлены
            # (то что не в errors)
            error_packages = set()
            for err in errors:
                # Формат "Ошибка при установке <name>"
                for pkg_name in self.packages.keys():
                    if pkg_name in err:
                        error_packages.add(pkg_name)
            installed = [p for p in self.packages.keys() if p not in error_packages]

        except Exception as e:
            log_error(f"{self.MODULE_ID}: Критическая ошибка установки: {e}")
            errors.append(f"Критическая ошибка: {e}")

        needs_restart = PipInstaller.has_pending_restart()

        result = {
            'success': len(errors) == 0,
            'installed': installed,
            'errors': errors,
            'needs_restart': needs_restart,
            'total': self._total_count,
        }

        if result['success']:
            log_info(
                f"{self.MODULE_ID}: Установка завершена успешно "
                f"({len(installed)}/{self._total_count})"
            )
            self.report_progress(100, "Установка завершена")
        else:
            log_warning(
                f"{self.MODULE_ID}: Установка завершена с ошибками: "
                f"{len(installed)}/{self._total_count} успешно, "
                f"ошибок: {len(errors)}"
            )

        return result
