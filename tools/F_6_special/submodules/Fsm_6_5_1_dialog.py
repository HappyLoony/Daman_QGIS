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
from typing import List, Optional

from qgis.PyQt.QtCore import QSettings, QTimer
from qgis.PyQt.QtWidgets import (
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from qgis.core import QgsProject

from Daman_QGIS.core.base_responsive_dialog import BaseResponsiveDialog
from Daman_QGIS.utils import log_error, log_info

from .Fsm_6_5_2_scanner import FileLockScanner, LockedFile, ScanResult
from .Fsm_6_5_3_closer import (
    CloseResult,
    close_local_files,
    close_network_files,
    is_unc_path,
    parse_unc_path,
)
from .Fsm_6_5_4_credential_dialog import Fsm_6_5_4_CredentialDialog
from .Fsm_6_5_5_confirm_dialog import Fsm_6_5_5_ConfirmDialog


# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------
_COLOR_OK = "#006600"
_COLOR_WARN = "#CC6600"
_COLOR_ERR = "#CC0000"

_COLUMNS = ["Файл", "Папка", "Пользователь", "Компьютер"]


class Fsm_6_5_1_Dialog(BaseResponsiveDialog):
    """Диалог проверки блокировок файлов."""

    WIDTH_RATIO = 0.58
    HEIGHT_RATIO = 0.65
    MIN_WIDTH = 650
    MAX_WIDTH = 1000
    MIN_HEIGHT = 450
    MAX_HEIGHT = 700

    SETTINGS_KEY_FOLDER = "Daman_QGIS/F_6_5/last_folder"

    def __init__(self, parent=None):
        super().__init__(parent)

        self._current_folder: Optional[str] = None
        self._last_result: Optional[ScanResult] = None

        self._setup_ui()
        self._load_settings()

        log_info("Fsm_6_5_1: Диалог инициализирован")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        """Настроить интерфейс."""
        self.setWindowTitle("F_6_5 Проверка блокировок файлов")

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

        self._btn_close_all = QPushButton("Закрыть у всех")
        self._btn_close_all.setMinimumWidth(120)
        self._btn_close_all.setToolTip(
            "Принудительно закрыть файлы (требует права администратора)"
        )
        self._btn_close_all.setEnabled(False)
        self._btn_close_all.clicked.connect(self._on_close_all)

        btn_layout.addWidget(self._btn_refresh)
        btn_layout.addWidget(self._btn_close_all)
        btn_layout.addStretch()

        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def _load_settings(self) -> None:
        """Загрузить сохраненные настройки (без запуска сканирования)."""
        settings = QSettings()
        saved_folder = settings.value(self.SETTINGS_KEY_FOLDER, "")
        if saved_folder and os.path.isdir(saved_folder):
            self._current_folder = os.path.normpath(saved_folder)
            self._edt_folder.setText(self._current_folder)
            self._btn_refresh.setEnabled(True)

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
        """Установить папку (без автосканирования)."""
        folder = os.path.normpath(folder)
        self._current_folder = folder
        self._edt_folder.setText(folder)
        self._btn_refresh.setEnabled(True)
        self._save_settings()

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
        self._btn_close_all.setEnabled(False)
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
            self._last_result = result
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

        # Кнопка "Закрыть у всех" активна если есть closeable файлы
        self._btn_close_all.setEnabled(
            bool(self._get_closeable_files())
        )

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
            # Для soft lock: "Пользователь (Программа)" или просто программу
            user_display = lf.locked_by_user
            if lf.lock_source == "Открыт в программе":
                if lf.locked_by_user and lf.lock_program:
                    user_display = f"{lf.locked_by_user} ({lf.lock_program})"
                elif lf.lock_program:
                    user_display = lf.lock_program

            items = [
                lf.file_name,
                lf.relative_path,
                user_display,
                lf.locked_by_host or "--",
            ]

            for col, text in enumerate(items):
                item = QTableWidgetItem(text)
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
    # Закрытие файлов
    # ------------------------------------------------------------------
    _NON_CLOSEABLE_SOURCES = {"Открыт в программе", "Мусор (застрявший .dwl)"}

    def _get_closeable_files(self) -> List[LockedFile]:
        """Файлы которые можно закрыть принудительно."""
        if not self._last_result:
            return []
        return [
            lf
            for lf in self._last_result.locked_files
            if lf.lock_source not in self._NON_CLOSEABLE_SOURCES
        ]

    def _on_close_all(self) -> None:
        """Обработчик кнопки 'Закрыть у всех'."""
        closeable = self._get_closeable_files()
        if not closeable:
            return

        # 1. Подтверждение
        confirm = Fsm_6_5_5_ConfirmDialog(closeable, parent=self)
        if confirm.exec() != Fsm_6_5_5_ConfirmDialog.DialogCode.Accepted:
            return

        # 2. Определить тип пути
        folder = self._current_folder or ""
        use_network = is_unc_path(folder)

        close_result: Optional[CloseResult] = None

        if use_network:
            # 3a. Сетевой: запросить credentials
            server, basepath = parse_unc_path(folder)
            cred_dlg = Fsm_6_5_4_CredentialDialog(server, parent=self)
            if cred_dlg.exec() != Fsm_6_5_4_CredentialDialog.DialogCode.Accepted:
                return

            creds = cred_dlg.get_credentials()
            if not creds:
                return

            username, domain, password = creds
            log_info(
                f"Fsm_6_5_1: Closing network files on \\\\{server}\\{basepath}"
            )

            self._lbl_status.setText("Закрытие файлов на сервере...")
            self._lbl_status.setStyleSheet(
                f"font-weight: bold; color: {_COLOR_WARN};"
            )
            self._btn_close_all.setEnabled(False)
            self._btn_refresh.setEnabled(False)
            QApplication.processEvents()

            close_result = close_network_files(
                server, basepath, username, domain, password,
                progress_callback=self._on_close_progress,
            )
        else:
            # 3b. Локальный: RestartManager
            file_paths = [lf.file_path for lf in closeable]
            log_info(
                f"Fsm_6_5_1: Closing {len(file_paths)} local files"
            )

            self._lbl_status.setText("Закрытие локальных файлов...")
            self._lbl_status.setStyleSheet(
                f"font-weight: bold; color: {_COLOR_WARN};"
            )
            self._btn_close_all.setEnabled(False)
            self._btn_refresh.setEnabled(False)
            QApplication.processEvents()

            close_result = close_local_files(
                file_paths,
                progress_callback=self._on_close_progress,
            )

        # 4. Показать результат
        self._show_close_result(close_result)

        # 5. Пересканировать через 2 сек
        QTimer.singleShot(2000, self._on_scan)

    def _on_close_progress(self, message: str) -> None:
        """Callback прогресса закрытия."""
        self._lbl_status.setText(message)
        QApplication.processEvents()

    def _show_close_result(self, result: Optional[CloseResult]) -> None:
        """Показать результат закрытия."""
        if result is None:
            return

        if result.errors:
            error_text = "\n".join(result.errors)
            QMessageBox.warning(
                self,
                "Ошибки при закрытии",
                f"Закрыто файлов: {result.closed_count}\n\n"
                f"Ошибки:\n{error_text}",
            )
        elif result.closed_count > 0:
            QMessageBox.information(
                self,
                "Файлы закрыты",
                f"Успешно закрыто: {result.closed_count} файлов.\n\n"
                f"Пересканирование через 2 секунды...",
            )
        else:
            QMessageBox.information(
                self,
                "Нет файлов для закрытия",
                "Не найдено открытых файлов на сервере "
                "в пределах указанной папки.",
            )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        """Сохранить настройки при закрытии."""
        self._save_settings()
        super().closeEvent(event)
