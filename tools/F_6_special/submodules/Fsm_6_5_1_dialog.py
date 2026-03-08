# -*- coding: utf-8 -*-
"""
Fsm_6_5_1: GUI диалог для F_6_5 Проверка блокировок файлов.

Предоставляет интерфейс для:
- Выбора папки для сканирования
- Сканирования заблокированных файлов (lock-маркеры + exclusive open)
- Отображения результатов в таблице с цветовой кодировкой
- Копирования отчёта в буфер обмена
"""

import os
from typing import Optional

from qgis.PyQt.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsProject

from Daman_QGIS.utils import log_error, log_info

from .Fsm_6_5_2_scanner import FileLockScanner, ScanResult


# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------
_COLOR_LOCK_KNOWN = QColor(255, 224, 224)     # Красноватый: известный пользователь
_COLOR_LOCK_UNKNOWN = QColor(255, 240, 224)   # Оранжеватый: неизвестный пользователь
_COLOR_OK = "#006600"
_COLOR_WARN = "#CC6600"
_COLOR_ERR = "#CC0000"

_COLUMNS = ["Файл", "Папка", "Пользователь", "Компьютер"]


class Fsm_6_5_1_Dialog(QDialog):
    """Диалог проверки блокировок файлов."""

    SETTINGS_KEY_FOLDER = "Daman_QGIS/F_6_5/last_folder"

    def __init__(self, parent=None):
        super().__init__(parent)

        self._current_folder: Optional[str] = None

        self._setup_ui()
        self._load_settings()

        log_info("Fsm_6_5_1: Диалог инициализирован")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        """Настроить интерфейс."""
        self.setWindowTitle("F_6_5 Проверка блокировок файлов")
        self.setMinimumWidth(800)
        self.setMinimumHeight(500)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # --- Папка ---
        folder_row = QHBoxLayout()
        self._edt_folder = QLineEdit()
        self._edt_folder.setPlaceholderText("Выберите папку для проверки")
        self._edt_folder.setReadOnly(True)

        self._btn_browse = QPushButton("...")
        self._btn_browse.setMaximumWidth(40)
        self._btn_browse.setToolTip("Выбрать папку")
        self._btn_browse.clicked.connect(self._on_browse)

        folder_row.addWidget(self._edt_folder)
        folder_row.addWidget(self._btn_browse)
        layout.addLayout(folder_row)

        # Прогресс
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setTextVisible(True)
        layout.addWidget(self._progress)

        # --- Таблица результатов ---
        result_group = QGroupBox("Результаты")
        result_layout = QVBoxLayout(result_group)

        self._table = QTableWidget()
        self._table.setColumnCount(len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._table.setAlternatingRowColors(False)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        result_layout.addWidget(self._table)
        layout.addWidget(result_group, stretch=1)

        # --- Статистика ---
        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._lbl_status)

        # --- Кнопка обновления ---
        btn_layout = QHBoxLayout()

        self._btn_refresh = QPushButton("Обновить")
        self._btn_refresh.setMinimumWidth(100)
        self._btn_refresh.setToolTip("Повторное сканирование")
        self._btn_refresh.setEnabled(False)
        self._btn_refresh.clicked.connect(self._on_scan)

        btn_layout.addWidget(self._btn_refresh)
        btn_layout.addStretch()

        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def _load_settings(self) -> None:
        """Загрузить сохраненные настройки."""
        settings = QSettings()
        saved_folder = settings.value(self.SETTINGS_KEY_FOLDER, "")
        if saved_folder and os.path.isdir(saved_folder):
            self._set_folder(saved_folder)

    def _save_settings(self) -> None:
        """Сохранить настройки."""
        if self._current_folder:
            QSettings().setValue(self.SETTINGS_KEY_FOLDER, self._current_folder)

    # ------------------------------------------------------------------
    # Выбор папки
    # ------------------------------------------------------------------
    def _on_browse(self) -> None:
        """Обработчик выбора папки."""
        start_dir = self._current_folder or ""
        if not start_dir:
            project_home = QgsProject.instance().homePath()
            if project_home:
                start_dir = project_home

        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку для проверки блокировок",
            start_dir,
        )
        if folder:
            self._set_folder(folder)

    def _set_folder(self, folder: str) -> None:
        """Установить папку и запустить сканирование."""
        self._current_folder = folder
        self._edt_folder.setText(folder)
        self._save_settings()
        self._on_scan()

    # ------------------------------------------------------------------
    # Сканирование
    # ------------------------------------------------------------------
    def _on_scan(self) -> None:
        """Запуск сканирования."""
        if not self._current_folder or not os.path.isdir(self._current_folder):
            return

        log_info(f"Fsm_6_5_1: Сканирование папки: {self._current_folder}")

        # Подготовка UI
        self._btn_refresh.setEnabled(False)
        self._btn_browse.setEnabled(False)
        self._table.setRowCount(0)
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._lbl_status.setText("Сканирование...")
        self._lbl_status.setStyleSheet(f"font-weight: bold; color: {_COLOR_WARN};")
        QApplication.processEvents()

        # Сканирование
        try:
            scanner = FileLockScanner(self._current_folder)
            result = scanner.scan(progress_callback=self._on_progress)
            self._display_results(result)
        except Exception as exc:
            log_error(f"Fsm_6_5_1: Ошибка сканирования: {exc}")
            self._lbl_status.setText(f"Ошибка: {exc}")
            self._lbl_status.setStyleSheet(
                f"font-weight: bold; color: {_COLOR_ERR};"
            )

        # Восстановление UI
        self._progress.setVisible(False)
        self._btn_refresh.setEnabled(True)
        self._btn_browse.setEnabled(True)

    def _on_progress(self, current: int, total: int) -> None:
        """Callback прогресса сканирования."""
        if total > 0:
            pct = int(current / total * 100)
            self._progress.setValue(pct)
            self._progress.setFormat(f"{current} / {total} файлов")
        QApplication.processEvents()

    # ------------------------------------------------------------------
    # Отображение результатов
    # ------------------------------------------------------------------
    def _display_results(self, result: ScanResult) -> None:
        """Заполнить таблицу результатами."""
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(result.locked_files))

        for row, lf in enumerate(result.locked_files):
            # Определить цвет строки
            bg = (
                _COLOR_LOCK_KNOWN
                if lf.locked_by_user != "Неизвестно"
                else _COLOR_LOCK_UNKNOWN
            )

            items = [
                lf.file_name,
                lf.relative_path,
                lf.locked_by_user,
                lf.locked_by_host,
            ]

            for col, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setBackground(bg)
                self._table.setItem(row, col, item)

        self._table.setSortingEnabled(True)

        # Статистика
        locked_count = len(result.locked_files)
        duration_sec = result.scan_duration_ms / 1000

        if locked_count == 0:
            self._lbl_status.setText(
                f"Все файлы свободны. "
                f"Проверено: {result.total_files_scanned} файлов "
                f"в {result.total_dirs_scanned} папках "
                f"за {duration_sec:.1f} сек"
            )
            self._lbl_status.setStyleSheet(
                f"font-weight: bold; color: {_COLOR_OK};"
            )
        else:
            self._lbl_status.setText(
                f"Заблокировано: {locked_count} из {result.total_files_scanned} файлов "
                f"({result.total_dirs_scanned} папок, {duration_sec:.1f} сек)"
            )
            self._lbl_status.setStyleSheet(
                f"font-weight: bold; color: {_COLOR_ERR};"
            )
        # Ошибки доступа и пропущенные записи
        extra_info = []
        if result.errors:
            extra_info.append(f"Ошибки доступа: {len(result.errors)}")
        if result.skipped_entries > 0:
            extra_info.append(f"Пропущено записей: {result.skipped_entries}")
        if extra_info:
            current = self._lbl_status.text()
            self._lbl_status.setText(
                f"{current} | {' | '.join(extra_info)}"
            )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        """Сохранить настройки при закрытии."""
        self._save_settings()
        super().closeEvent(event)
