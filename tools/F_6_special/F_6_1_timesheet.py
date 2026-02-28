# -*- coding: utf-8 -*-
"""
F_6_1: Табель - Обработка табелей сотрудников.

Функция для анализа и объединения рабочих табелей сотрудников
с валидацией и генерацией сводных отчетов.

Генерирует:
- Объединенный_табель.xlsx - все табели в одном файле
- Сводный_табель.xlsx - матрица сотрудники x шифры проектов

Использует QgsTask для асинхронной обработки без блокировки UI.
"""

from datetime import datetime, date
from typing import Optional, List, Set, Tuple, Dict, Any

from qgis.PyQt.QtWidgets import QWidget
from qgis.PyQt.QtCore import QDate, pyqtSignal, QObject
from qgis.core import QgsTask, QgsApplication

from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.managers.reference import EmployeeReferenceManager
from Daman_QGIS.managers.reference.submodules import ProductionCalendarManager

from .submodules.Fsm_6_1_1_dialog import Fsm_6_1_1_Dialog
from .submodules.Fsm_6_1_2_validator import (
    TimesheetValidator, ValidationResult, format_validation_report
)
from .submodules.Fsm_6_1_3_parser import (
    TimesheetData, parse_timesheets_from_folder, get_manager_timesheet
)
from .submodules.Fsm_6_1_4_merger import MergedTimesheetGenerator
from .submodules.Fsm_6_1_5_summary import SummaryTimesheetGenerator


class TimesheetProcessingTask(QgsTask):
    """
    Фоновая задача обработки табелей.

    Выполняет все операции (парсинг, валидация, генерация) в отдельном потоке,
    не блокируя UI QGIS.
    """

    def __init__(
        self,
        source_folder: str,
        dest_folder: str,
        end_date: date,
        target_month: int,
        target_year: int,
        valid_surnames: Set[str],
        signals: 'TaskSignals'
    ):
        """
        Инициализация задачи.

        Args:
            source_folder: Папка с исходными табелями
            dest_folder: Папка назначения
            end_date: Дата окончания расчетного периода
            target_month: Целевой месяц
            target_year: Целевой год
            valid_surnames: Множество валидных фамилий
            signals: Объект сигналов для обновления UI
        """
        super().__init__("Обработка табелей", QgsTask.CanCancel)
        self.source_folder = source_folder
        self.dest_folder = dest_folder
        self.end_date = end_date
        self.target_month = target_month
        self.target_year = target_year
        self.valid_surnames = valid_surnames
        self.signals = signals

        # Результаты обработки
        self.timesheets: List[TimesheetData] = []
        self.valid_timesheets: List[TimesheetData] = []
        self.validation_report: str = ""
        self.output_files: List[str] = []
        self.error_message: Optional[str] = None
        self.employee_rates: Dict[str, float] = {}

    def run(self) -> bool:
        """
        Выполнить обработку в фоновом потоке.

        Returns:
            True при успешном завершении
        """
        try:
            # Фаза 1: Парсинг файлов (10-30%)
            self.signals.log_message.emit(
                f"=== Фаза 1: Поиск табелей за {self.target_month} месяц {self.target_year} года ===\n"
            )
            self.signals.log_message.emit(f"Фамилий в базе: {len(self.valid_surnames)}\n")
            self.setProgress(10)

            if self.isCanceled():
                return False

            self.timesheets = parse_timesheets_from_folder(
                self.source_folder,
                valid_surnames=self.valid_surnames,
                target_month=self.target_month
            )

            # Автоматически добавляем табель руководителя из фиксированной папки
            manager_timesheet = get_manager_timesheet(
                valid_surnames=self.valid_surnames,
                target_month=self.target_month
            )
            if manager_timesheet:
                self.timesheets.append(manager_timesheet)
                self.signals.log_message.emit(
                    f"Добавлен табель руководителя: {manager_timesheet.filename}\n"
                )

            if not self.timesheets:
                self.signals.log_message.emit(
                    f"Не найдено подходящих табелей.\n"
                    f"Ожидаются файлы вида: Фамилия_{self.target_month}.xlsx\n"
                    f"где Фамилия есть в базе сотрудников."
                )
                return True  # Не ошибка, просто нет данных

            self.signals.log_message.emit(f"Найдено подходящих файлов: {len(self.timesheets)}\n")
            self.setProgress(30)

            if self.isCanceled():
                return False

            # Фаза 2: Валидация (30-50%)
            self.signals.log_message.emit("=== Фаза 2: Валидация ===\n")

            # Валидатор с учётом end_day (день из GUI)
            validator = TimesheetValidator(
                target_month=self.target_month,
                end_day=self.end_date.day
            )
            validation_results = validator.validate_all(self.timesheets)

            # Получаем норму часов для расчёта отклонения
            norm_hours = None
            try:
                calendar_manager = ProductionCalendarManager()
                # Норма от начала месяца до выбранной даты включительно
                period_start = date(self.target_year, self.target_month, 1)
                period_end = date(self.target_year, self.target_month, self.end_date.day)
                norm_hours = calendar_manager.get_work_hours_for_period(
                    period_start, period_end
                )
            except Exception as e:
                log_warning(f"F_6_1: Не удалось получить производственный календарь: {e}")
                # Если не удалось получить норму - отклонение не показываем

            # Собираем ставки сотрудников для расчёта индивидуальных норм
            self.employee_rates = {}
            for ts, _ in validation_results:
                if ts.fio:
                    rate = validator.get_employee_rate(ts.fio)
                    self.employee_rates[ts.fio] = rate

            self.validation_report = format_validation_report(
                validation_results,
                use_html=True,
                norm_hours=norm_hours,
                end_day=self.end_date.day,
                employee_rates=self.employee_rates
            )
            self.signals.log_message.emit(self.validation_report)
            self.signals.log_message.emit("")

            self.valid_timesheets = validator.get_valid_timesheets(validation_results)
            self.setProgress(50)

            if self.isCanceled():
                return False

            if not self.valid_timesheets:
                self.signals.log_message.emit("\nНет валидных табелей для обработки.")
                return True

            # Фаза 3: Генерация объединенного табеля (50-75%)
            self.signals.log_message.emit("\n=== Фаза 3: Генерация Объединенного табеля ===\n")

            merger = MergedTimesheetGenerator()
            merged_path = merger.generate(
                self.valid_timesheets,
                self.dest_folder,
                end_day=self.end_date.day
            )

            if merged_path:
                self.signals.log_message.emit(f"Создан: {merged_path}\n")
                self.output_files.append(merged_path)
            else:
                self.signals.log_message.emit("Ошибка при создании объединенного табеля\n")

            self.setProgress(75)

            if self.isCanceled():
                return False

            # Фаза 4: Генерация сводного табеля (75-100%)
            self.signals.log_message.emit("=== Фаза 4: Генерация Сводного табеля ===\n")

            summary_generator = SummaryTimesheetGenerator()
            summary_path = summary_generator.generate(
                self.valid_timesheets, self.dest_folder, self.end_date,
                self.employee_rates
            )

            if summary_path:
                self.signals.log_message.emit(f"Создан: {summary_path}\n")
                self.output_files.append(summary_path)
            else:
                self.signals.log_message.emit("Ошибка при создании сводного табеля\n")

            self.setProgress(100)
            return True

        except Exception as e:
            self.error_message = str(e)
            log_error(f"F_6_1: Ошибка в фоновой задаче: {e}")
            return False

    def finished(self, result: bool) -> None:
        """
        Вызывается при завершении задачи (в главном потоке).

        Args:
            result: Результат выполнения run()
        """
        if self.isCanceled():
            self.signals.task_canceled.emit()
        elif result:
            self.signals.task_completed.emit(
                len(self.valid_timesheets),
                len(self.timesheets),
                self.output_files
            )
        else:
            self.signals.task_failed.emit(self.error_message or "Неизвестная ошибка")


class TaskSignals(QObject):
    """Сигналы для связи между QgsTask и UI."""

    # Сигнал для добавления сообщения в лог
    log_message = pyqtSignal(str)

    # Сигнал успешного завершения (valid_count, total_count, output_files)
    task_completed = pyqtSignal(int, int, list)

    # Сигнал ошибки
    task_failed = pyqtSignal(str)

    # Сигнал отмены
    task_canceled = pyqtSignal()


class F_6_1_Timesheet(BaseTool):
    """Обработка табелей сотрудников."""

    def __init__(self, iface):
        super().__init__(iface)
        self.dialog: Optional[Fsm_6_1_1_Dialog] = None
        self._valid_surnames: Optional[Set[str]] = None
        self._task: Optional[TimesheetProcessingTask] = None
        self._task_signals: Optional[TaskSignals] = None

    def _get_valid_surnames(self) -> Set[str]:
        """Получить множество фамилий сотрудников из базы (lowercase)."""
        if self._valid_surnames is None:
            employee_manager = EmployeeReferenceManager()
            employees = employee_manager.get_employees()
            self._valid_surnames = {
                emp.get('last_name', '').lower()
                for emp in employees
                if emp.get('last_name')
            }
            log_info(f"F_6_1: Загружено {len(self._valid_surnames)} фамилий из базы сотрудников")
        return self._valid_surnames

    def run(self) -> None:
        """Запуск функции."""
        log_info("F_6_1: Запуск функции Табель")

        # Создаем диалог
        self.dialog = Fsm_6_1_1_Dialog(self.iface.mainWindow())
        self.dialog.set_run_callback(self._on_process)

        # Показываем диалог
        self.dialog.exec()

    def _on_process(self, source_folder: str, dest_folder: str, end_date: QDate) -> None:
        """
        Обработчик запуска обработки.

        Запускает фоновую задачу QgsTask для обработки табелей
        без блокировки UI.

        Args:
            source_folder: Папка с исходными табелями
            dest_folder: Папка назначения
            end_date: Дата окончания расчетного периода
        """
        # Конвертируем QDate в Python date
        report_end_date = date(end_date.year(), end_date.month(), end_date.day())
        target_month = end_date.month()
        target_year = end_date.year()

        log_info(
            f"F_6_1: Начало обработки. Источник: {source_folder}, "
            f"Назначение: {dest_folder}, Период до: {report_end_date}, "
            f"Целевой месяц: {target_month}, Год: {target_year}"
        )

        if not self.dialog:
            return

        self.dialog.set_controls_enabled(False)
        self.dialog.show_progress(True)
        self.dialog.clear_log()

        # Получаем фамилии из базы ДО запуска задачи (в главном потоке)
        # Это единственная сетевая операция в главном потоке,
        # но она кэшируется и выполняется быстро
        valid_surnames = self._get_valid_surnames()

        # Создаем сигналы для связи с UI
        self._task_signals = TaskSignals()
        self._task_signals.log_message.connect(self._on_task_log)
        self._task_signals.task_completed.connect(self._on_task_completed)
        self._task_signals.task_failed.connect(self._on_task_failed)
        self._task_signals.task_canceled.connect(self._on_task_canceled)

        # Создаем и запускаем фоновую задачу
        self._task = TimesheetProcessingTask(
            source_folder=source_folder,
            dest_folder=dest_folder,
            end_date=report_end_date,
            target_month=target_month,
            target_year=target_year,
            valid_surnames=valid_surnames,
            signals=self._task_signals
        )

        # Передаем ссылку на задачу в диалог для очистки при закрытии
        if self.dialog:
            self.dialog.set_task_reference(self._task)

        # Подключаем прогресс
        self._task.progressChanged.connect(self._on_task_progress)

        # Добавляем задачу в менеджер задач QGIS
        QgsApplication.taskManager().addTask(self._task)
        log_info("F_6_1: Фоновая задача запущена")

    def _on_task_log(self, message: str) -> None:
        """Обработчик сообщений из фоновой задачи."""
        if self.dialog:
            # Проверяем содержит ли сообщение HTML разметку
            is_html = '<span' in message or '<br>' in message
            self.dialog.append_log(message, is_html=is_html)

    def _on_task_progress(self, progress: float) -> None:
        """Обработчик прогресса из фоновой задачи."""
        if self.dialog:
            self.dialog.set_progress(int(progress), 100)

    def _on_task_completed(self, valid_count: int, total_count: int, output_files: List[str]) -> None:
        """Обработчик успешного завершения фоновой задачи."""
        log_info(
            f"F_6_1: Фоновая задача завершена. "
            f"Валидных: {valid_count}/{total_count}, файлов: {len(output_files)}"
        )
        self._finish_processing(valid_count, total_count, output_files)

    def _on_task_failed(self, error_message: str) -> None:
        """Обработчик ошибки в фоновой задаче."""
        log_error(f"F_6_1: Ошибка в фоновой задаче: {error_message}")
        if self.dialog:
            self.dialog.append_log(f"\nКритическая ошибка: {error_message}")
        self._finish_processing(0, 0, [])

    def _on_task_canceled(self) -> None:
        """Обработчик отмены фоновой задачи."""
        log_info("F_6_1: Фоновая задача отменена пользователем")
        if self.dialog:
            self.dialog.append_log("\nОбработка отменена пользователем.")
        self._finish_processing(0, 0, [])

    def _finish_processing(
        self,
        valid_count: int,
        total_count: int,
        output_files: List[str]
    ) -> None:
        """
        Завершить обработку.

        Args:
            valid_count: Количество валидных табелей
            total_count: Общее количество табелей
            output_files: Список созданных файлов
        """
        if not self.dialog:
            return

        self.dialog.show_progress(False)
        self.dialog.set_controls_enabled(True)

        self.dialog.append_log("\n" + "=" * 40)
        self.dialog.append_log(f"Обработка завершена.")
        self.dialog.append_log(f"Валидных табелей: {valid_count} из {total_count}")

        if output_files:
            self.dialog.append_log(f"Создано файлов: {len(output_files)}")
            self.dialog.show_completion_message(valid_count, total_count, output_files)

        log_info(
            f"F_6_1: Обработка завершена. "
            f"Валидных: {valid_count}/{total_count}, файлов: {len(output_files)}"
        )
