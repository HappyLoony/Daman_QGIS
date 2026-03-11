# -*- coding: utf-8 -*-
"""
Fsm_6_3_1: GUI диалог для F_6_3 Список файлов в папке.

Предоставляет интерфейс для:
- Выбора папки для сканирования
- Отображения содержимого через QFileSystemModel + QTreeView
- Фильтрации по расширениям
- Экспорта списка в clipboard или TXT-файл
"""

import os
import getpass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple

from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QGroupBox, QTreeView,
    QCheckBox, QApplication, QHeaderView
)
from qgis.PyQt.QtCore import Qt, QSettings, QModelIndex, QDir
from qgis.PyQt.QtWidgets import QFileSystemModel
from qgis.core import QgsProject, Qgis

from Daman_QGIS.core.base_responsive_dialog import BaseResponsiveDialog
from Daman_QGIS.utils import log_info, log_error, format_file_size
from Daman_QGIS.constants import MESSAGE_INFO_DURATION


class Fsm_6_3_1_Dialog(BaseResponsiveDialog):
    """Диалог списка файлов в папке."""

    WIDTH_RATIO = 0.55
    HEIGHT_RATIO = 0.70
    MIN_WIDTH = 650
    MAX_WIDTH = 950
    MIN_HEIGHT = 480
    MAX_HEIGHT = 750

    SETTINGS_KEY_FOLDER = "Daman_QGIS/F_6_3/last_folder"
    SETTINGS_KEY_FILTER = "Daman_QGIS/F_6_3/extensions_filter"
    SETTINGS_KEY_SUBDIRS = "Daman_QGIS/F_6_3/include_subdirs"

    def __init__(self, parent=None):
        super().__init__(parent)

        self._current_folder: Optional[str] = None
        self._fs_model: Optional[QFileSystemModel] = None

        self._setup_ui()
        self._load_settings()

        log_info("Fsm_6_3_1: Диалог инициализирован")

    def _setup_ui(self) -> None:
        """Настроить интерфейс."""
        self.setWindowTitle("F_6_3 Список файлов в папке")

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # --- Группа: Папка ---
        folder_group = QGroupBox("Папка")
        folder_layout = QVBoxLayout(folder_group)

        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Выберите папку для сканирования")
        self.folder_edit.setReadOnly(True)

        self.folder_btn = QPushButton("...")
        self.folder_btn.setMaximumWidth(40)
        self.folder_btn.setToolTip("Выбрать папку")
        self.folder_btn.clicked.connect(self._on_folder_browse)

        folder_row.addWidget(self.folder_edit)
        folder_row.addWidget(self.folder_btn)
        folder_layout.addLayout(folder_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-weight: bold;")
        folder_layout.addWidget(self.status_label)

        layout.addWidget(folder_group)

        # --- Группа: Фильтр ---
        filter_group = QGroupBox("Фильтр расширений")
        filter_layout = QHBoxLayout(filter_group)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(
            "*.dwg, *.docx, *.xlsx (пусто = все файлы)"
        )
        self.filter_edit.setToolTip(
            "Введите маски расширений через запятую.\n"
            "Пусто = показать все файлы."
        )
        self.filter_edit.textChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.filter_edit)

        self.subdirs_checkbox = QCheckBox("Включать подпапки")
        self.subdirs_checkbox.setToolTip(
            "Показывать файлы из подпапок в виде дерева"
        )
        filter_layout.addWidget(self.subdirs_checkbox)

        layout.addWidget(filter_group)

        # --- Группа: Содержимое ---
        content_group = QGroupBox("Содержимое")
        content_layout = QVBoxLayout(content_group)

        self.tree_view = QTreeView()
        self.tree_view.setSortingEnabled(True)
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setSelectionMode(
            QTreeView.SelectionMode.ExtendedSelection
        )
        content_layout.addWidget(self.tree_view)

        layout.addWidget(content_group, stretch=1)

        # --- Кнопки ---
        btn_layout = QHBoxLayout()

        self.copy_btn = QPushButton("Копировать список")
        self.copy_btn.setMinimumWidth(140)
        self.copy_btn.setToolTip("Копировать список файлов в буфер обмена")
        self.copy_btn.clicked.connect(self._on_copy_to_clipboard)
        self.copy_btn.setEnabled(False)

        self.txt_btn = QPushButton("Создать TXT файл")
        self.txt_btn.setMinimumWidth(140)
        self.txt_btn.setToolTip("Сохранить список в TXT-файл в выбранной папке")
        self.txt_btn.clicked.connect(self._on_create_txt)
        self.txt_btn.setEnabled(False)

        btn_layout.addWidget(self.copy_btn)
        btn_layout.addWidget(self.txt_btn)
        btn_layout.addStretch()

        self.close_btn = QPushButton("Закрыть")
        self.close_btn.setMinimumWidth(100)
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

    # --- Settings ---

    def _load_settings(self) -> None:
        """Загрузить сохраненные настройки."""
        settings = QSettings()
        saved_folder = settings.value(self.SETTINGS_KEY_FOLDER, "")
        saved_filter = settings.value(self.SETTINGS_KEY_FILTER, "")
        saved_subdirs = settings.value(
            self.SETTINGS_KEY_SUBDIRS, False, type=bool
        )

        if saved_filter:
            self.filter_edit.setText(saved_filter)
        self.subdirs_checkbox.setChecked(saved_subdirs)

        if saved_folder and os.path.isdir(saved_folder):
            self._set_folder(saved_folder)

    def _save_settings(self) -> None:
        """Сохранить настройки."""
        settings = QSettings()
        if self._current_folder:
            settings.setValue(self.SETTINGS_KEY_FOLDER, self._current_folder)
        settings.setValue(self.SETTINGS_KEY_FILTER, self.filter_edit.text())
        settings.setValue(
            self.SETTINGS_KEY_SUBDIRS, self.subdirs_checkbox.isChecked()
        )

    # --- Folder selection ---

    def _on_folder_browse(self) -> None:
        """Обработчик выбора папки."""
        start_dir = self._current_folder or ""
        if not start_dir:
            project_home = QgsProject.instance().homePath()
            if project_home:
                start_dir = project_home

        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку для сканирования",
            start_dir
        )
        if folder:
            self._set_folder(folder)

    def _set_folder(self, folder: str) -> None:
        """Установить папку и обновить модель."""
        self._current_folder = folder
        self.folder_edit.setText(folder)
        self._save_settings()
        self._update_model()

    # --- File system model ---

    def _parse_filter(self) -> List[str]:
        """Парсинг строки фильтра в список масок."""
        text = self.filter_edit.text().strip()
        if not text:
            return []

        filters = []
        for part in text.split(","):
            part = part.strip()
            if part:
                if not part.startswith("*"):
                    part = "*." + part.lstrip(".")
                filters.append(part)
        return filters

    def _update_model(self) -> None:
        """Обновить QFileSystemModel для текущей папки."""
        if not self._current_folder or not os.path.isdir(self._current_folder):
            return

        # Cleanup old model to release file watcher threads
        if self._fs_model is not None:
            self._fs_model.deleteLater()

        self._fs_model = QFileSystemModel()
        self._fs_model.setReadOnly(True)
        self._fs_model.setRootPath(self._current_folder)

        # Применить фильтр расширений
        filters = self._parse_filter()
        if filters:
            self._fs_model.setNameFilters(filters)
            self._fs_model.setNameFilterDisables(False)

        # Настроить отображение подпапок
        if not self.subdirs_checkbox.isChecked():
            self._fs_model.setFilter(
                QDir.Filter.Files | QDir.Filter.NoDotAndDotDot
            )
        else:
            self._fs_model.setFilter(
                QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot
            )

        self.tree_view.setModel(self._fs_model)
        self.tree_view.setRootIndex(
            self._fs_model.index(self._current_folder)
        )

        # Настроить колонки
        header = self.tree_view.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, self._fs_model.columnCount()):
            header.setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )

        # Сортировка по имени
        self.tree_view.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        # Обновить статистику после загрузки модели
        self._fs_model.directoryLoaded.connect(self._on_directory_loaded)

        # Включить кнопки экспорта
        self.copy_btn.setEnabled(True)
        self.txt_btn.setEnabled(True)

        log_info(f"Fsm_6_3_1: Папка установлена: {self._current_folder}")

    def _on_directory_loaded(self, path: str) -> None:
        """Обработчик загрузки директории (обновление статистики)."""
        if path != self._current_folder:
            return
        self._update_status()

    def _on_filter_changed(self) -> None:
        """Обработчик изменения фильтра расширений."""
        self._save_settings()
        if self._current_folder:
            self._update_model()

    def _update_status(self) -> None:
        """Обновить статус с количеством файлов и папок."""
        if not self._fs_model or not self._current_folder:
            return

        root_index = self._fs_model.index(self._current_folder)
        file_count = 0
        dir_count = 0
        total_size = 0

        row_count = self._fs_model.rowCount(root_index)
        for row in range(row_count):
            child = self._fs_model.index(row, 0, root_index)
            if self._fs_model.isDir(child):
                dir_count += 1
            else:
                file_count += 1
                total_size += self._fs_model.size(child)

        size_str = format_file_size(total_size)
        filter_text = self.filter_edit.text().strip()
        filter_info = f", фильтр: {filter_text}" if filter_text else ""

        self.status_label.setText(
            f"Найдено: {file_count} файлов, {dir_count} папок "
            f"({size_str}{filter_info})"
        )
        self.status_label.setStyleSheet(
            "font-weight: bold; color: #006600;" if file_count > 0
            else "font-weight: bold; color: #CC6600;"
        )

    # --- Data collection ---

    def _collect_visible_entries(self) -> List[Tuple[str, bool, int, float]]:
        """
        Собрать видимые записи из модели.

        Returns:
            Список кортежей (имя, is_dir, размер_байт, mtime_timestamp)
        """
        entries: List[Tuple[str, bool, int, float]] = []

        if not self._fs_model or not self._current_folder:
            return entries

        root_index = self._fs_model.index(self._current_folder)
        row_count = self._fs_model.rowCount(root_index)

        for row in range(row_count):
            idx = self._fs_model.index(row, 0, root_index)
            name = self._fs_model.fileName(idx)
            is_dir = self._fs_model.isDir(idx)
            size = self._fs_model.size(idx) if not is_dir else 0
            file_path = self._fs_model.filePath(idx)

            try:
                mtime = os.path.getmtime(file_path)
            except OSError:
                mtime = 0.0

            entries.append((name, is_dir, size, mtime))

        return entries

    # --- Export: Clipboard ---

    def _on_copy_to_clipboard(self) -> None:
        """Копировать список файлов в буфер обмена."""
        entries = self._collect_visible_entries()
        if not entries:
            log_info("Fsm_6_3_1: Нет данных для копирования")
            return

        lines = []
        for name, is_dir, size, _mtime in entries:
            if is_dir:
                lines.append(f"[Папка] {name}")
            else:
                lines.append(f"{name}\t{format_file_size(size)}")

        text = "\n".join(lines)

        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)

        log_info(
            f"Fsm_6_3_1: Скопировано в clipboard: {len(entries)} записей"
        )
        self.status_label.setText(
            f"Скопировано в буфер обмена: {len(entries)} записей"
        )
        self.status_label.setStyleSheet("font-weight: bold; color: #006600;")

    # --- Export: TXT ---

    def _on_create_txt(self) -> None:
        """Создать TXT-файл со списком."""
        if not self._current_folder:
            return

        entries = self._collect_visible_entries()
        if not entries:
            log_info("Fsm_6_3_1: Нет данных для экспорта")
            return

        now = datetime.now()
        timestamp_file = now.strftime("%Y_%m_%d %H_%M_%S")
        timestamp_report = now.strftime("%d.%m.%Y %H:%M:%S")

        filename = f"Содержание папки {timestamp_file}.txt"
        output_path = Path(self._current_folder) / filename

        try:
            username = getpass.getuser()
        except Exception as e:
            log_error(f"Fsm_6_3_1: Ошибка getpass: {e}")
            username = "Unknown"

        # Формирование отчёта
        total_size = 0
        file_count = 0
        dir_count = 0
        file_lines = []

        for name, is_dir, size, mtime in entries:
            if is_dir:
                dir_count += 1
                file_lines.append(f"[Папка] {name}")
            else:
                file_count += 1
                total_size += size
                mtime_str = datetime.fromtimestamp(mtime).strftime(
                    "%d.%m.%Y %H:%M"
                ) if mtime > 0 else ""
                file_lines.append(
                    f"{name}\t{format_file_size(size)}\t{mtime_str}"
                )

        filter_text = self.filter_edit.text().strip()
        filter_info = filter_text if filter_text else "все файлы"

        report_lines = [
            "Содержание папки",
            f"Дата: {timestamp_report}",
            f"Пользователь: {username}",
            f"Папка: {self._current_folder}",
            f"Фильтр: {filter_info}",
            "---",
        ]
        report_lines.extend(file_lines)
        report_lines.extend([
            "---",
            f"Файлов: {file_count}, папок: {dir_count}",
            f"Общий размер: {format_file_size(total_size)}",
        ])

        report_text = "\n".join(report_lines) + "\n"

        try:
            output_path.write_text(report_text, encoding="utf-8")
            log_info(f"Fsm_6_3_1: TXT создан: {output_path}")
            self.status_label.setText(
                f"Файл создан: {filename}"
            )
            self.status_label.setStyleSheet(
                "font-weight: bold; color: #006600;"
            )
        except OSError as e:
            log_error(f"Fsm_6_3_1: Ошибка записи TXT: {e}")
            self.status_label.setText(f"Ошибка записи: {e}")
            self.status_label.setStyleSheet(
                "font-weight: bold; color: #CC0000;"
            )

    def closeEvent(self, event) -> None:
        """Сохранить настройки при закрытии."""
        self._save_settings()
        super().closeEvent(event)
