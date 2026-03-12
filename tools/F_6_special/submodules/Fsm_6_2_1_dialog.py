# -*- coding: utf-8 -*-
"""
Fsm_6_2_1: GUI диалог для F_6_2 Сформировать тома PDF.

Предоставляет интерфейс для:
- Выбора папки "Выпуск новый"
- Отображения найденных файлов (DWG, DOCX, XLSX)
- Отображения прогресса и лога конвертации
"""

import os
import glob
from typing import Optional, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from qgis.core import QgsTask

from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QFileDialog, QProgressBar,
    QGroupBox, QMessageBox
)
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QFont

from Daman_QGIS.core.base_responsive_dialog import BaseResponsiveDialog
from Daman_QGIS.utils import log_info, log_error


class Fsm_6_2_1_Dialog(BaseResponsiveDialog):
    """Диалог формирования томов PDF."""

    WIDTH_RATIO = 0.48
    HEIGHT_RATIO = 0.65
    MIN_WIDTH = 580
    MAX_WIDTH = 850
    MIN_HEIGHT = 450
    MAX_HEIGHT = 700

    SETTINGS_KEY_SOURCE = "Daman_QGIS/F_6_2/source_folder"

    def __init__(self, parent=None):
        super().__init__(parent)

        self._source_folder: Optional[str] = None
        self._on_run_callback: Optional[Callable[[str], None]] = None
        self._running_task: Optional['QgsTask'] = None

        self._setup_ui()
        self._load_settings()
        self._update_run_button_state()

        log_info("Fsm_6_2_1: Диалог инициализирован")

    def _setup_ui(self) -> None:
        """Настроить интерфейс."""
        self.setWindowTitle("F_6_2 Сформировать тома PDF")

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # --- Группа: Папка выпуска ---
        source_group = QGroupBox("Папка выпуска")
        source_layout = QVBoxLayout(source_group)

        folder_row = QHBoxLayout()
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText(
            "Выберите папку 'Выпуск новый'"
        )
        self.source_edit.setReadOnly(True)

        self.source_btn = QPushButton("...")
        self.source_btn.setMaximumWidth(40)
        self.source_btn.clicked.connect(self._on_source_browse)

        folder_row.addWidget(self.source_edit)
        folder_row.addWidget(self.source_btn)
        source_layout.addLayout(folder_row)

        hint_label = QLabel(
            "Пример: A:\\2025\\Судак (25-П-33)\\Выпуск новый"
        )
        hint_label.setStyleSheet("color: #888888; font-style: italic;")
        source_layout.addWidget(hint_label)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-weight: bold;")
        source_layout.addWidget(self.status_label)

        layout.addWidget(source_group)

        # --- Группа: Лог ---
        log_group = QGroupBox("Лог операций")
        log_layout = QVBoxLayout(log_group)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_edit)

        layout.addWidget(log_group)

        # --- Прогресс-бар ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # --- Кнопки ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.run_btn = QPushButton("Сформировать")
        self.run_btn.setMinimumWidth(150)
        self.run_btn.clicked.connect(self._on_run)
        self.run_btn.setEnabled(False)

        self.close_btn = QPushButton("Закрыть")
        self.close_btn.setMinimumWidth(100)
        self.close_btn.clicked.connect(self.close)

        btn_layout.addWidget(self.run_btn)
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)

    def _load_settings(self) -> None:
        """Загрузить сохраненные настройки."""
        settings = QSettings()
        saved_folder = settings.value(self.SETTINGS_KEY_SOURCE, "")
        if saved_folder and os.path.isdir(saved_folder):
            self._set_source_folder(saved_folder)

    def _save_settings(self) -> None:
        """Сохранить настройки."""
        settings = QSettings()
        if self._source_folder:
            settings.setValue(self.SETTINGS_KEY_SOURCE, self._source_folder)

    def _on_source_browse(self) -> None:
        """Обработчик выбора папки."""
        start_dir = self._source_folder or ""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку 'Выпуск новый'",
            start_dir
        )
        if folder:
            self._set_source_folder(folder)

    def _set_source_folder(self, folder: str) -> None:
        """Установить выбранную папку и обновить статус."""
        folder = os.path.normpath(folder)
        self._source_folder = folder
        self.source_edit.setText(folder)
        self._save_settings()

        # Проверить содержимое
        edit_fmt = os.path.join(folder, "Редактируемый формат")
        if not os.path.isdir(edit_fmt):
            self.status_label.setText(
                "Папка 'Редактируемый формат' не найдена"
            )
            self.status_label.setStyleSheet(
                "font-weight: bold; color: #CC0000;"
            )
            self._update_run_button_state()
            return

        # Подсчитать файлы
        dwg_count = len(glob.glob(
            os.path.join(edit_fmt, "Графическая часть", "*.dwg")
        ))
        docx_count = 0
        xlsx_count = 0
        volume_count = 0

        text_dir = os.path.join(edit_fmt, "Текстовая часть")
        if os.path.isdir(text_dir):
            for entry in os.listdir(text_dir):
                vol_dir = os.path.join(text_dir, entry)
                if not os.path.isdir(vol_dir):
                    continue
                volume_count += 1
                for f in os.listdir(vol_dir):
                    if f.startswith("~$"):
                        continue
                    ext = os.path.splitext(f)[1].lower()
                    if ext == ".docx":
                        docx_count += 1
                    elif ext == ".xlsx":
                        xlsx_count += 1

        total = dwg_count + docx_count + xlsx_count
        self.status_label.setText(
            f"Найдено: DWG: {dwg_count}, DOCX: {docx_count}, "
            f"XLSX: {xlsx_count} (томов: {volume_count}). "
            f"Всего файлов: {total}"
        )
        self.status_label.setStyleSheet(
            "font-weight: bold; color: #006600;" if total > 0
            else "font-weight: bold; color: #CC6600;"
        )

        self._update_run_button_state()

    def _update_run_button_state(self) -> None:
        """Обновить доступность кнопки Сформировать."""
        enabled = False
        if self._source_folder:
            edit_fmt = os.path.join(
                self._source_folder, "Редактируемый формат"
            )
            enabled = os.path.isdir(edit_fmt)
        self.run_btn.setEnabled(enabled)

    def _on_run(self) -> None:
        """Обработчик кнопки Сформировать."""
        if not self._source_folder or not self._on_run_callback:
            return
        self._on_run_callback(self._source_folder)

    # --- Публичные методы для управления из F_6_2 ---

    def set_run_callback(self, callback: Callable[[str], None]) -> None:
        """Установить callback для кнопки Сформировать."""
        self._on_run_callback = callback

    def set_task_reference(self, task: 'QgsTask') -> None:
        """Сохранить ссылку на задачу для отмены при закрытии."""
        self._running_task = task

    def append_log(self, text: str, is_html: bool = False) -> None:
        """Добавить текст в лог."""
        if is_html:
            self.log_edit.insertHtml(text)
        else:
            self.log_edit.append(text.rstrip())
        # Прокрутить вниз
        scrollbar = self.log_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_log(self) -> None:
        """Очистить лог."""
        self.log_edit.clear()

    def show_progress(self, visible: bool) -> None:
        """Показать/скрыть прогресс-бар."""
        self.progress_bar.setVisible(visible)

    def set_progress(self, value: int, maximum: int) -> None:
        """Установить значение прогресса."""
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(value)

    def set_controls_enabled(self, enabled: bool) -> None:
        """Включить/выключить элементы управления."""
        self.source_btn.setEnabled(enabled)
        self.run_btn.setEnabled(enabled)

    def closeEvent(self, event) -> None:
        """Обработка закрытия диалога."""
        if self._running_task and self._running_task.isActive():
            reply = QMessageBox.question(
                self,
                "Отменить?",
                "Задача ещё выполняется. Отменить и закрыть?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            self._running_task.cancel()

        super().closeEvent(event)
