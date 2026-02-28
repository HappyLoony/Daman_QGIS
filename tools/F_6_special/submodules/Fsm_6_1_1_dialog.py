# -*- coding: utf-8 -*-
"""
GUI диалог для функции F_6_1 Табель.

Предоставляет интерфейс для:
- Выбора папки с исходными табелями
- Выбора папки назначения
- Отображения результатов валидации
- Запуска обработки
"""

import os
from pathlib import Path
from typing import Optional, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from qgis.core import QgsTask

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QFileDialog, QProgressBar,
    QGroupBox, QMessageBox, QDateEdit
)
from qgis.PyQt.QtCore import Qt, QSettings, QStandardPaths, QDate, QLocale
from qgis.PyQt.QtGui import QFont

from Daman_QGIS.utils import log_info, log_error
from .Fsm_6_1_3_parser import find_timesheet_folder, TIMESHEETS_BASE_FOLDER


class Fsm_6_1_1_Dialog(QDialog):
    """Диалог обработки табелей сотрудников."""

    SETTINGS_KEY_DEST = "Daman_QGIS/F_6_1/dest_folder"

    # Названия месяцев на русском (родительный падеж)
    MONTH_NAMES = [
        "", "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря"
    ]

    def __init__(self, parent=None):
        super().__init__(parent)

        self._source_folder: Optional[str] = None
        self._dest_folder: Optional[str] = None
        self._on_run_callback: Optional[Callable[[str, str, QDate], None]] = None
        self._running_task: Optional['QgsTask'] = None

        self._setup_ui()
        self._load_settings()
        self._update_source_folder()  # Автопоиск папки по текущей дате
        self._update_run_button_state()

        log_info("Fsm_6_1_1: Диалог инициализирован")

    def _setup_ui(self) -> None:
        """Настроить интерфейс."""
        self.setWindowTitle("F_6_1 Табель - Обработка табелей сотрудников")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Группа: Источник табелей (автоопределение по дате)
        source_group = QGroupBox("Источник табелей (определяется автоматически)")
        source_layout = QVBoxLayout(source_group)

        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Папка определяется по выбранной дате")
        self.source_edit.setReadOnly(True)
        self.source_edit.setStyleSheet("color: #666666;")

        self.source_status_label = QLabel()
        self.source_status_label.setStyleSheet("font-style: italic;")

        source_layout.addWidget(self.source_edit)
        source_layout.addWidget(self.source_status_label)
        layout.addWidget(source_group)

        # Группа: Папка назначения
        dest_group = QGroupBox("Папка назначения")
        dest_layout = QHBoxLayout(dest_group)

        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText("Папка для сохранения результатов")
        self.dest_edit.setReadOnly(True)

        self.dest_btn = QPushButton("...")
        self.dest_btn.setMaximumWidth(40)
        self.dest_btn.clicked.connect(self._on_dest_browse)

        dest_layout.addWidget(self.dest_edit)
        dest_layout.addWidget(self.dest_btn)
        layout.addWidget(dest_group)

        # Группа: Результаты валидации
        results_group = QGroupBox("Результаты валидации")
        results_layout = QVBoxLayout(results_group)

        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setMinimumHeight(250)

        # Моноширинный шрифт для логов
        font = QFont("Consolas", 9)
        if not font.exactMatch():
            font = QFont("Courier New", 9)
        self.results_text.setFont(font)

        results_layout.addWidget(self.results_text)
        layout.addWidget(results_group)

        # Прогресс-бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Группа: Расчетный период
        period_group = QGroupBox("Расчетный период")
        period_layout = QVBoxLayout(period_group)

        # Строка с выбором даты
        date_row_layout = QHBoxLayout()

        date_label = QLabel("Дата окончания периода:")
        date_row_layout.addWidget(date_label)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setMinimumWidth(120)
        self.date_edit.dateChanged.connect(self._on_date_changed)
        date_row_layout.addWidget(self.date_edit)

        date_row_layout.addStretch()
        period_layout.addLayout(date_row_layout)

        # Подпись с описанием периода
        self.period_label = QLabel()
        self.period_label.setStyleSheet("color: #666666; font-style: italic;")
        period_layout.addWidget(self.period_label)

        layout.addWidget(period_group)

        # Обновляем подпись периода
        self._update_period_label()

        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        self.run_btn = QPushButton("Сформировать")
        self.run_btn.setMinimumWidth(120)
        self.run_btn.clicked.connect(self._on_run)

        self.close_btn = QPushButton("Закрыть")
        self.close_btn.setMinimumWidth(100)
        self.close_btn.clicked.connect(self.close)

        buttons_layout.addWidget(self.run_btn)
        buttons_layout.addWidget(self.close_btn)
        layout.addLayout(buttons_layout)

    def _load_settings(self) -> None:
        """Загрузить сохраненные настройки."""
        settings = QSettings()

        # Папка назначения - Рабочий стол по умолчанию (работает для любой локализации Windows)
        default_dest = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        dest = settings.value(self.SETTINGS_KEY_DEST, default_dest)
        if dest and os.path.isdir(dest):
            self._dest_folder = dest
            self.dest_edit.setText(dest)
        elif os.path.isdir(default_dest):
            self._dest_folder = default_dest
            self.dest_edit.setText(default_dest)

    def _save_settings(self) -> None:
        """Сохранить настройки."""
        settings = QSettings()

        if self._dest_folder:
            settings.setValue(self.SETTINGS_KEY_DEST, self._dest_folder)

    def _update_run_button_state(self) -> None:
        """Обновить состояние кнопки запуска."""
        enabled = bool(self._source_folder and self._dest_folder)
        self.run_btn.setEnabled(enabled)

    def _update_source_folder(self) -> None:
        """Автоматически определить папку источника по выбранной дате."""
        selected_date = self.date_edit.date()
        year = selected_date.year()
        month = selected_date.month()

        # Ищем папку по дате
        folder = find_timesheet_folder(year, month)

        if folder and os.path.isdir(folder):
            self._source_folder = folder
            self.source_edit.setText(folder)
            self.source_status_label.setText("")
            self.source_status_label.setStyleSheet("color: #006600; font-style: italic;")

            # Подсчитаем файлы
            xlsx_files = list(Path(folder).glob("*.xlsx"))
            xlsx_files = [f for f in xlsx_files if not f.name.startswith("~$")]
            self.source_status_label.setText(f"Найдено файлов: {len(xlsx_files)}")
        else:
            self._source_folder = None
            self.source_edit.setText("")
            self.source_status_label.setText(
                f"Папка табелей за {month:02d}.{year} не найдена. "
                f"Проверьте доступность сетевого диска."
            )
            self.source_status_label.setStyleSheet("color: #cc0000; font-style: italic;")

        self._update_run_button_state()

    def _on_dest_browse(self) -> None:
        """Обработчик выбора папки назначения."""
        start_dir = self._dest_folder or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)

        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку для сохранения результатов",
            start_dir,
            QFileDialog.Option.ShowDirsOnly
        )

        if folder:
            self._dest_folder = folder
            self.dest_edit.setText(folder)
            self._update_run_button_state()
            self._save_settings()

    def _on_date_changed(self, new_date: QDate) -> None:
        """Обработчик изменения даты."""
        self._update_period_label()
        self._update_source_folder()  # Автопоиск папки при изменении даты

    def _update_period_label(self) -> None:
        """Обновить подпись с описанием периода."""
        selected_date = self.date_edit.date()
        day = selected_date.day()
        month = selected_date.month()
        year = selected_date.year()

        month_name = self.MONTH_NAMES[month]

        self.period_label.setText(
            f"Учтено с 1 {month_name} по {day} {month_name} {year} года включительно"
        )

    def _on_run(self) -> None:
        """Обработчик кнопки запуска."""
        if not self._source_folder or not self._dest_folder:
            return

        if self._on_run_callback:
            self.clear_log()
            selected_date = self.date_edit.date()
            self._on_run_callback(self._source_folder, self._dest_folder, selected_date)

    def set_run_callback(self, callback: Callable[[str, str, QDate], None]) -> None:
        """
        Установить callback для кнопки запуска.

        Args:
            callback: Функция (source_folder, dest_folder, end_date) -> None
        """
        self._on_run_callback = callback

    def append_log(self, text: str, is_html: bool = False) -> None:
        """
        Добавить текст в лог.

        Args:
            text: Текст для добавления
            is_html: Если True, текст содержит HTML разметку
        """
        if is_html:
            self.results_text.insertHtml(text + "<br>")
        else:
            self.results_text.append(text)
        # Прокрутка вниз
        scrollbar = self.results_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def append_html(self, html: str) -> None:
        """
        Добавить HTML в лог.

        Args:
            html: HTML текст для добавления
        """
        self.results_text.insertHtml(html)
        # Прокрутка вниз
        scrollbar = self.results_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_log(self) -> None:
        """Очистить лог."""
        self.results_text.clear()

    def set_log(self, text: str) -> None:
        """
        Установить текст лога.

        Args:
            text: Полный текст лога
        """
        self.results_text.setPlainText(text)

    def set_html(self, html: str) -> None:
        """
        Установить HTML в лог.

        Args:
            html: HTML текст
        """
        self.results_text.setHtml(html)

    def show_progress(self, visible: bool = True) -> None:
        """
        Показать/скрыть прогресс-бар.

        Args:
            visible: Видимость прогресс-бара
        """
        self.progress_bar.setVisible(visible)

    def set_progress(self, value: int, maximum: int = 100) -> None:
        """
        Установить значение прогресса.

        Args:
            value: Текущее значение
            maximum: Максимальное значение
        """
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(value)

    def set_controls_enabled(self, enabled: bool) -> None:
        """
        Включить/отключить элементы управления.

        Args:
            enabled: Включены ли элементы
        """
        self.dest_btn.setEnabled(enabled)
        self.date_edit.setEnabled(enabled)
        self.run_btn.setEnabled(enabled and bool(self._source_folder and self._dest_folder))

    def show_completion_message(
        self,
        valid_count: int,
        total_count: int,
        output_files: list
    ) -> None:
        """
        Показать сообщение о завершении.

        Args:
            valid_count: Количество валидных табелей
            total_count: Общее количество табелей
            output_files: Список созданных файлов
        """
        if valid_count == 0:
            QMessageBox.warning(
                self,
                "Результат",
                f"Ни один табель не прошел валидацию.\n"
                f"Обработано файлов: {total_count}"
            )
            return

        files_text = "\n".join(f"- {f}" for f in output_files)
        QMessageBox.information(
            self,
            "Готово",
            f"Обработка завершена.\n\n"
            f"Валидных табелей: {valid_count} из {total_count}\n\n"
            f"Созданные файлы:\n{files_text}"
        )

    @property
    def source_folder(self) -> Optional[str]:
        """Папка с исходными табелями."""
        return self._source_folder

    @property
    def dest_folder(self) -> Optional[str]:
        """Папка назначения."""
        return self._dest_folder

    @property
    def selected_date(self) -> QDate:
        """Выбранная дата окончания периода."""
        return self.date_edit.date()

    @property
    def selected_month(self) -> int:
        """Месяц из выбранной даты (для поиска файлов)."""
        return self.date_edit.date().month()

    @property
    def selected_year(self) -> int:
        """Год из выбранной даты."""
        return self.date_edit.date().year()

    def set_task_reference(self, task: Optional['QgsTask']) -> None:
        """
        Установить ссылку на выполняемую задачу для очистки при закрытии.

        Args:
            task: Выполняемая QgsTask или None
        """
        self._running_task = task

    def closeEvent(self, event) -> None:
        """Обработка закрытия диалога - отмена задачи если она выполняется."""
        if self._running_task is not None:
            try:
                if not self._running_task.isCanceled():
                    self._running_task.cancel()
                    log_info("Fsm_6_1_1: Диалог закрыт, задача отменена")
            except RuntimeError:
                # QgsTask C++ объект уже удалён QGIS (задача завершилась)
                pass
            self._running_task = None
        super().closeEvent(event)
