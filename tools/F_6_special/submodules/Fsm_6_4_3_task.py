# -*- coding: utf-8 -*-
"""
Fsm_6_4_3: FileSelectionTask - фоновая задача копирования/перемещения файлов.

QgsTask для неблокирующего выполнения файловых операций.
Паттерн: F_6_2 (custom QgsTask + custom signals).
"""

import os
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional

from qgis.PyQt.QtCore import pyqtSignal, QObject
from qgis.core import QgsTask

from Daman_QGIS.utils import log_info, log_error

from .Fsm_6_4_2_matcher import MatchedFile


class FileSelectionTaskSignals(QObject):
    """Сигналы для связи между QgsTask и UI."""
    log_message = pyqtSignal(str)
    task_completed = pyqtSignal(dict)  # results dict
    task_failed = pyqtSignal(str)
    task_canceled = pyqtSignal()


def _safe_path(path: str) -> str:
    """
    Добавляет \\\\?\\ prefix для длинных путей на Windows.

    Windows ограничивает пути 260 символами (MAX_PATH).
    Prefix снимает ограничение для NTFS.
    """
    if os.name == 'nt' and len(path) > 240 and not path.startswith('\\\\?\\'):
        return '\\\\?\\' + os.path.abspath(path)
    return path


class FileSelectionTask(QgsTask):
    """
    Фоновая задача копирования/перемещения файлов.

    Выполняется в отдельном потоке через QgsTaskManager.
    Периодически проверяет отмену. Генерирует TXT отчёт.
    """

    # Режимы операции
    MODE_COPY = "copy"
    MODE_MOVE = "move"

    def __init__(
        self,
        matched_files: List[MatchedFile],
        dest_folder: str,
        mode: str,
        create_ext_folders: bool,
        source_folder: str,
        signals: FileSelectionTaskSignals,
    ):
        mode_label = "Копирование" if mode == self.MODE_COPY else "Перемещение"
        super().__init__(f"Выборка файлов ({mode_label})", QgsTask.CanCancel)

        self.matched_files = matched_files
        self.dest_folder = dest_folder
        self.mode = mode
        self.create_ext_folders = create_ext_folders
        self.source_folder = source_folder
        self.signals = signals
        self.error_message: Optional[str] = None

        # Результаты
        self._results: Dict[str, Any] = {
            'processed': 0,
            'success': 0,
            'skipped': 0,
            'errors': [],
            'total_size': 0,
            'report_path': '',
        }

    def run(self) -> bool:
        """Выполнить операцию в фоновом потоке."""
        try:
            log_info("Fsm_6_4_3: Начало выполнения задачи")

            # Фаза 1: Подготовка (0-5%)
            self.setProgress(0)
            self._log("Подготовка папки назначения...")
            os.makedirs(_safe_path(self.dest_folder), exist_ok=True)

            if self.isCanceled():
                return False

            self.setProgress(5)

            # Фаза 2: Копирование/перемещение (5-90%)
            total = len(self.matched_files)
            if total == 0:
                self._log("Нет файлов для обработки")
                self.setProgress(90)
            else:
                self._process_files(total)

            if self.isCanceled():
                return False

            # Фаза 3: Отчёт (90-100%)
            self.setProgress(90)
            self._log("Генерация отчёта...")
            self._generate_report()
            self.setProgress(100)

            return True

        except Exception as e:
            import traceback
            self.error_message = f"{str(e)}\n{traceback.format_exc()}"
            log_error(f"Fsm_6_4_3: Ошибка: {self.error_message}")
            return False

    def _process_files(self, total: int) -> None:
        """Копирование/перемещение файлов с прогрессом."""
        mode_label = "Копирование" if self.mode == self.MODE_COPY else "Перемещение"

        for i, mf in enumerate(self.matched_files):
            if self.isCanceled():
                self._log(f"Операция отменена на файле {i + 1}/{total}")
                return

            # Прогресс: 5% + (85% * i / total)
            progress = 5 + int(85 * i / max(total, 1))
            self.setProgress(progress)

            # Определение папки назначения
            if self.create_ext_folders and mf.extension:
                ext_folder_name = mf.extension.lstrip('.')
                dest_dir = os.path.join(self.dest_folder, ext_folder_name)
                os.makedirs(_safe_path(dest_dir), exist_ok=True)
            else:
                dest_dir = self.dest_folder

            dest_path = os.path.join(dest_dir, mf.name)
            src_path = mf.full_path

            self._results['processed'] += 1

            # Проверка конфликта
            if os.path.exists(_safe_path(dest_path)):
                self._log(f"  Пропуск (существует): {mf.name}")
                self._results['skipped'] += 1
                continue

            # Выполнение операции
            try:
                safe_src = _safe_path(src_path)
                safe_dest = _safe_path(dest_path)

                if self.mode == self.MODE_COPY:
                    shutil.copy2(safe_src, safe_dest)
                else:
                    shutil.move(safe_src, safe_dest)

                self._results['success'] += 1
                self._results['total_size'] += mf.size
                self._log(f"  {mode_label}: {mf.name}")

            except (OSError, shutil.Error) as e:
                error_msg = f"{mf.name}: {str(e)}"
                self._results['errors'].append(error_msg)
                self._log(f"  Ошибка: {error_msg}")

    def _generate_report(self) -> None:
        """Генерация TXT отчёта в папку назначения."""
        now = datetime.now()
        report_name = f"Отчет_выборки_{now.strftime('%Y_%m_%d_%H_%M_%S')}.txt"
        report_path = os.path.join(self.dest_folder, report_name)

        mode_label = "Копирование" if self.mode == self.MODE_COPY else "Перемещение"
        r = self._results

        lines = [
            "Отчет по выборке файлов",
            f"Дата: {now.strftime('%d.%m.%Y %H:%M:%S')}",
            f"Режим: {mode_label}",
            f"Исходная папка: {self.source_folder}",
            f"Папка выборки: {self.dest_folder}",
            "---",
            f"Обработано строк: {r['processed']}",
            f"Успешно: {r['success']}",
            f"Пропущено (существуют): {r['skipped']}",
            f"Ошибок: {len(r['errors'])}",
            f"Общий размер: {self._format_size(r['total_size'])}",
        ]

        if r['errors']:
            lines.append("---")
            lines.append("Ошибки:")
            for err in r['errors']:
                lines.append(f"  - {err}")

        lines.append("---")

        try:
            with open(_safe_path(report_path), 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))

            self._results['report_path'] = report_path
            self._log(f"Отчёт сохранён: {report_name}")

        except OSError as e:
            self._log(f"Не удалось сохранить отчёт: {e}")

    def finished(self, result: bool) -> None:
        """Вызывается в main thread после завершения."""
        if self.isCanceled():
            log_info("Fsm_6_4_3: Задача отменена пользователем")
            self.signals.task_canceled.emit()
        elif result:
            log_info(
                f"Fsm_6_4_3: Задача завершена. "
                f"Успешно: {self._results['success']}, "
                f"ошибок: {len(self._results['errors'])}"
            )
            self.signals.task_completed.emit(self._results)
        else:
            log_error(f"Fsm_6_4_3: Задача завершена с ошибкой: {self.error_message}")
            self.signals.task_failed.emit(self.error_message or "Unknown error")

    def _log(self, message: str) -> None:
        """Отправка сообщения в UI через сигнал."""
        self.signals.log_message.emit(message)

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Форматирование размера файла."""
        if size_bytes < 1024:
            return f"{size_bytes} Б"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} КБ"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} МБ"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} ГБ"
