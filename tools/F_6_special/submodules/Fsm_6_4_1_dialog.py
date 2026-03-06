# -*- coding: utf-8 -*-
"""
Fsm_6_4_1: Dialog - wizard для выборки файлов по списку.

QDialog с QStackedWidget (4 страницы):
- Страница 0: Выбор папки + автосканирование
- Страница 1: Ввод списка + live preview
- Страница 2: Настройки операции (расширения, режим)
- Страница 3: Прогресс + отчёт
"""

import os
from datetime import datetime
from typing import Dict, List, Optional, Set

from qgis.PyQt.QtCore import Qt, QSettings, QTimer
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsApplication, QgsProject

from Daman_QGIS.utils import log_info, log_error, format_file_size

from .Fsm_6_4_2_matcher import FileMatcher, MatchResult
from .Fsm_6_4_3_task import (
    FileSelectionTask,
    FileSelectionTaskSignals,
)


# QSettings keys
_SK_FOLDER = "Daman_QGIS/F_6_4/last_folder"
_SK_SUBDIRS = "Daman_QGIS/F_6_4/include_subdirs"
_SK_MODE = "Daman_QGIS/F_6_4/operation_mode"
_SK_EXT_FOLDERS = "Daman_QGIS/F_6_4/create_ext_folders"


class Fsm_6_4_1_Dialog(QDialog):
    """
    Wizard для выборки файлов по списку.

    4 страницы QStackedWidget с навигацией Назад/Далее/Выполнить.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("F_6_4: Выборка файлов по списку")
        self.setMinimumSize(800, 550)

        self._settings = QSettings()

        # Состояние
        self._matcher: Optional[FileMatcher] = None
        self._last_match_result: Optional[MatchResult] = None
        self._task: Optional[FileSelectionTask] = None
        self._task_signals: Optional[FileSelectionTaskSignals] = None

        # Debounce timer для live preview
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(300)
        self._preview_timer.timeout.connect(self._update_preview)

        # Чекбоксы расширений (динамические)
        self._ext_checkboxes: Dict[str, QCheckBox] = {}

        self._build_ui()
        self._restore_settings()
        self._update_navigation()

    # ------------------------------------------------------------------
    # UI Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Построение интерфейса."""
        layout = QVBoxLayout(self)

        # Стек страниц
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_page_folder())
        self._stack.addWidget(self._build_page_list())
        self._stack.addWidget(self._build_page_settings())
        self._stack.addWidget(self._build_page_progress())
        layout.addWidget(self._stack, stretch=1)

        # Навигация
        nav_layout = QHBoxLayout()
        nav_layout.addStretch()

        self._btn_back = QPushButton("Назад")
        self._btn_back.clicked.connect(self._on_back)
        nav_layout.addWidget(self._btn_back)

        self._btn_next = QPushButton("Далее")
        self._btn_next.clicked.connect(self._on_next)
        nav_layout.addWidget(self._btn_next)

        self._btn_execute = QPushButton("Выполнить")
        self._btn_execute.clicked.connect(self._on_execute)
        nav_layout.addWidget(self._btn_execute)

        self._btn_close = QPushButton("Закрыть")
        self._btn_close.clicked.connect(self.close)
        nav_layout.addWidget(self._btn_close)

        layout.addLayout(nav_layout)

    def _build_page_folder(self) -> QWidget:
        """Страница 0: Выбор папки."""
        page = QWidget()
        layout = QVBoxLayout(page)

        # Выбор папки
        grp_folder = QGroupBox("Исходная папка")
        folder_layout = QHBoxLayout(grp_folder)

        self._edit_folder = QLineEdit()
        self._edit_folder.setReadOnly(True)
        self._edit_folder.setPlaceholderText("Выберите папку для сканирования...")
        folder_layout.addWidget(self._edit_folder, stretch=1)

        btn_browse = QPushButton("...")
        btn_browse.setFixedWidth(40)
        btn_browse.clicked.connect(self._on_browse_folder)
        folder_layout.addWidget(btn_browse)

        layout.addWidget(grp_folder)

        # Опции
        self._chk_subdirs = QCheckBox("Включая подпапки")
        self._chk_subdirs.stateChanged.connect(self._on_subdirs_changed)
        layout.addWidget(self._chk_subdirs)

        # Статус
        self._lbl_folder_status = QLabel("Папка не выбрана")
        self._lbl_folder_status.setStyleSheet("color: gray;")
        layout.addWidget(self._lbl_folder_status)

        layout.addStretch()
        return page

    def _build_page_list(self) -> QWidget:
        """Страница 1: Ввод списка + live preview."""
        page = QWidget()
        layout = QVBoxLayout(page)

        splitter = QSplitter(Qt.Horizontal)

        # Левая часть: ввод списка
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        lbl_list = QLabel("Список имён файлов (по одному на строку):")
        left_layout.addWidget(lbl_list)

        self._edit_list = QPlainTextEdit()
        self._edit_list.setPlaceholderText(
            "Введите имена файлов без расширений.\n"
            "Поддерживаются маски: * (любые символы), ? (один символ).\n\n"
            "Примеры:\n"
            "  Пояснительная записка\n"
            "  Том_*\n"
            "  Схема_?"
        )
        self._edit_list.textChanged.connect(self._on_list_text_changed)
        left_layout.addWidget(self._edit_list)

        # Кнопки списка
        list_btn_layout = QHBoxLayout()

        btn_load_txt = QPushButton("Загрузить из TXT")
        btn_load_txt.clicked.connect(self._on_load_from_txt)
        list_btn_layout.addWidget(btn_load_txt)

        btn_clear = QPushButton("Очистить")
        btn_clear.clicked.connect(self._edit_list.clear)
        list_btn_layout.addWidget(btn_clear)

        list_btn_layout.addStretch()
        left_layout.addLayout(list_btn_layout)

        splitter.addWidget(left_widget)

        # Правая часть: preview совпадений
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        lbl_preview = QLabel("Preview совпадений:")
        right_layout.addWidget(lbl_preview)

        self._tbl_preview = QTableWidget()
        self._tbl_preview.setColumnCount(3)
        self._tbl_preview.setHorizontalHeaderLabels(["Имя файла", "Расширение", "Размер"])
        self._tbl_preview.setEditTriggers(QTableWidget.NoEditTriggers)
        self._tbl_preview.setSelectionBehavior(QTableWidget.SelectRows)
        self._tbl_preview.horizontalHeader().setStretchLastSection(True)
        right_layout.addWidget(self._tbl_preview)

        self._lbl_preview_status = QLabel("Введите имена файлов для поиска")
        self._lbl_preview_status.setStyleSheet("color: gray;")
        right_layout.addWidget(self._lbl_preview_status)

        splitter.addWidget(right_widget)
        splitter.setSizes([350, 450])

        layout.addWidget(splitter)
        return page

    def _build_page_settings(self) -> QWidget:
        """Страница 2: Настройки операции."""
        page = QWidget()
        layout = QVBoxLayout(page)

        # Расширения
        grp_ext = QGroupBox("Расширения для обработки")
        self._ext_layout = QGridLayout(grp_ext)

        # Кнопки выбора расширений
        ext_btn_layout = QHBoxLayout()
        btn_select_all = QPushButton("Выбрать все")
        btn_select_all.clicked.connect(lambda: self._set_all_extensions(True))
        ext_btn_layout.addWidget(btn_select_all)

        btn_deselect_all = QPushButton("Снять все")
        btn_deselect_all.clicked.connect(lambda: self._set_all_extensions(False))
        ext_btn_layout.addWidget(btn_deselect_all)

        ext_btn_layout.addStretch()
        self._ext_layout.addLayout(ext_btn_layout, 0, 0, 1, 4)

        layout.addWidget(grp_ext)

        # Режим операции
        grp_mode = QGroupBox("Параметры")
        mode_layout = QVBoxLayout(grp_mode)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Режим:"))
        self._cmb_mode = QComboBox()
        self._cmb_mode.addItems(["Копирование", "Перемещение"])
        mode_row.addWidget(self._cmb_mode)
        mode_row.addStretch()
        mode_layout.addLayout(mode_row)

        self._chk_ext_folders = QCheckBox("Создать подпапки по расширениям")
        mode_layout.addWidget(self._chk_ext_folders)

        # Папка назначения
        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel("Папка назначения:"))
        self._edit_dest = QLineEdit()
        self._edit_dest.setReadOnly(True)
        dest_row.addWidget(self._edit_dest, stretch=1)

        btn_dest = QPushButton("...")
        btn_dest.setFixedWidth(40)
        btn_dest.clicked.connect(self._on_browse_dest)
        dest_row.addWidget(btn_dest)
        mode_layout.addLayout(dest_row)

        layout.addWidget(grp_mode)

        # Финальный preview
        self._lbl_settings_summary = QLabel("")
        self._lbl_settings_summary.setStyleSheet("color: #2e7d32; font-weight: bold;")
        layout.addWidget(self._lbl_settings_summary)

        layout.addStretch()
        return page

    def _build_page_progress(self) -> QWidget:
        """Страница 3: Прогресс + отчёт."""
        page = QWidget()
        layout = QVBoxLayout(page)

        # Прогресс
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        layout.addWidget(self._progress_bar)

        # Лог
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        layout.addWidget(self._log_text, stretch=1)

        # Кнопки результатов
        result_layout = QHBoxLayout()

        self._btn_open_folder = QPushButton("Открыть папку")
        self._btn_open_folder.clicked.connect(self._on_open_dest_folder)
        self._btn_open_folder.setVisible(False)
        result_layout.addWidget(self._btn_open_folder)

        self._btn_cancel_task = QPushButton("Отменить")
        self._btn_cancel_task.clicked.connect(self._on_cancel_task)
        result_layout.addWidget(self._btn_cancel_task)

        result_layout.addStretch()
        layout.addLayout(result_layout)

        return page

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _update_navigation(self) -> None:
        """Обновление состояния кнопок навигации."""
        page = self._stack.currentIndex()

        self._btn_back.setVisible(page > 0 and page < 3)
        self._btn_next.setVisible(page < 2)
        self._btn_execute.setVisible(page == 2)
        self._btn_close.setVisible(page == 0 or page == 3)

        # Блокировка "Далее" по условиям
        if page == 0:
            # Папка должна быть выбрана
            self._btn_next.setEnabled(self._matcher is not None)
        elif page == 1:
            # Список не пустой и есть совпадения
            has_matches = (
                self._last_match_result is not None
                and self._last_match_result.matched_count > 0
            )
            self._btn_next.setEnabled(has_matches)
        elif page == 2:
            # Хотя бы одно расширение выбрано
            has_ext = any(cb.isChecked() for cb in self._ext_checkboxes.values())
            self._btn_execute.setEnabled(has_ext)

    def _on_back(self) -> None:
        """Переход на предыдущую страницу."""
        page = self._stack.currentIndex()
        if page > 0:
            self._stack.setCurrentIndex(page - 1)
            self._update_navigation()

    def _on_next(self) -> None:
        """Переход на следующую страницу."""
        page = self._stack.currentIndex()

        if page == 0:
            # Переход к вводу списка
            self._stack.setCurrentIndex(1)
        elif page == 1:
            # Переход к настройкам -- построить чекбоксы расширений
            self._build_extension_checkboxes()
            self._update_dest_folder()
            self._update_settings_summary()
            self._stack.setCurrentIndex(2)

        self._update_navigation()

    # ------------------------------------------------------------------
    # Page 0: Folder
    # ------------------------------------------------------------------

    def _on_browse_folder(self) -> None:
        """Выбор исходной папки."""
        default_folder = self._settings.value(_SK_FOLDER, "")
        if not default_folder or not os.path.isdir(str(default_folder)):
            project_home = QgsProject.instance().homePath()
            default_folder = project_home if project_home else ""

        folder = QFileDialog.getExistingDirectory(
            self, "Выберите исходную папку", str(default_folder)
        )
        if not folder:
            return

        self._edit_folder.setText(folder)
        self._settings.setValue(_SK_FOLDER, folder)

        self._scan_folder(folder)

    def _on_subdirs_changed(self) -> None:
        """Изменение режима подпапок -- пересканировать."""
        folder = self._edit_folder.text()
        if folder and os.path.isdir(folder):
            self._scan_folder(folder)

    def _scan_folder(self, folder: str) -> None:
        """Сканирование папки."""
        include_subdirs = self._chk_subdirs.isChecked()
        self._settings.setValue(_SK_SUBDIRS, include_subdirs)

        self._matcher = FileMatcher(folder, include_subdirs)
        self._matcher.scan_folder()

        ext_count = len(self._matcher.extensions)
        file_count = self._matcher.file_count

        skipped = self._matcher.skipped_count
        skip_text = f" (пропущено: {skipped})" if skipped > 0 else ""
        self._lbl_folder_status.setText(
            f"Найдено: {file_count} файлов, {ext_count} расширений{skip_text}"
        )
        self._lbl_folder_status.setStyleSheet(
            "color: #2e7d32;" if file_count > 0 else "color: #c62828;"
        )

        self._update_navigation()
        log_info(f"Fsm_6_4_1: Просканировано {file_count} файлов в {folder}")

    # ------------------------------------------------------------------
    # Page 1: List + Preview
    # ------------------------------------------------------------------

    def _on_list_text_changed(self) -> None:
        """Текст изменён -- запустить debounce timer."""
        self._preview_timer.start()

    def _update_preview(self) -> None:
        """Обновление preview совпадений."""
        if not self._matcher:
            return

        text = self._edit_list.toPlainText()
        patterns = [line.strip() for line in text.split('\n') if line.strip()]

        if not patterns:
            self._tbl_preview.setRowCount(0)
            self._lbl_preview_status.setText("Введите имена файлов для поиска")
            self._lbl_preview_status.setStyleSheet("color: gray;")
            self._last_match_result = None
            self._update_navigation()
            return

        # Поиск без фильтра расширений (все)
        result = self._matcher.find_matches(patterns)
        self._last_match_result = result

        # Заполнение таблицы
        self._tbl_preview.setRowCount(len(result.matched))
        for row, mf in enumerate(result.matched):
            self._tbl_preview.setItem(row, 0, QTableWidgetItem(mf.name))
            self._tbl_preview.setItem(row, 1, QTableWidgetItem(mf.extension))
            self._tbl_preview.setItem(row, 2, QTableWidgetItem(
                format_file_size(mf.size)
            ))

        self._tbl_preview.resizeColumnsToContents()

        # Статус
        matched_count = result.matched_count
        unmatched_count = len(result.unmatched)
        total_patterns = len(patterns)

        if matched_count > 0:
            status_text = (
                f"Совпадений: {matched_count} файлов "
                f"из {total_patterns} строк"
            )
            if unmatched_count > 0:
                status_text += f" (не найдено: {unmatched_count})"
            self._lbl_preview_status.setText(status_text)
            self._lbl_preview_status.setStyleSheet("color: #2e7d32;")
        else:
            self._lbl_preview_status.setText(
                f"Совпадений не найдено ({total_patterns} строк)"
            )
            self._lbl_preview_status.setStyleSheet("color: #c62828;")

        self._update_navigation()

    def _on_load_from_txt(self) -> None:
        """Загрузка списка из TXT файла."""
        folder = self._edit_folder.text() or ""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Загрузить список из файла", folder,
            "Текстовые файлы (*.txt);;Все файлы (*.*)"
        )
        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self._edit_list.setPlainText(content)
            log_info(f"Fsm_6_4_1: Загружен список из {file_path}")
        except UnicodeDecodeError:
            try:
                with open(file_path, 'r', encoding='cp1251') as f:
                    content = f.read()
                self._edit_list.setPlainText(content)
            except Exception as e:
                log_error(f"Fsm_6_4_1: Ошибка чтения файла: {e}")
                QMessageBox.warning(
                    self, "Ошибка",
                    f"Не удалось прочитать файл:\n{e}"
                )
        except Exception as e:
            log_error(f"Fsm_6_4_1: Ошибка чтения файла: {e}")
            QMessageBox.warning(
                self, "Ошибка",
                f"Не удалось прочитать файл:\n{e}"
            )

    # ------------------------------------------------------------------
    # Page 2: Settings
    # ------------------------------------------------------------------

    def _build_extension_checkboxes(self) -> None:
        """Создание чекбоксов расширений."""
        # Очистка старых чекбоксов (кроме кнопок на строке 0)
        for cb in self._ext_checkboxes.values():
            self._ext_layout.removeWidget(cb)
            cb.deleteLater()
        self._ext_checkboxes.clear()

        if not self._matcher:
            return

        extensions = self._matcher.extensions
        sorted_exts = sorted(extensions.keys())

        # Расположение в 4 колонки, начиная со строки 1
        for i, ext in enumerate(sorted_exts):
            count = extensions[ext]
            cb = QCheckBox(f"{ext} ({count})")
            cb.setChecked(True)
            cb.stateChanged.connect(self._on_extension_changed)
            self._ext_checkboxes[ext] = cb
            row = 1 + i // 4
            col = i % 4
            self._ext_layout.addWidget(cb, row, col)

    def _set_all_extensions(self, checked: bool) -> None:
        """Выбрать/снять все расширения."""
        for cb in self._ext_checkboxes.values():
            cb.setChecked(checked)

    def _on_extension_changed(self) -> None:
        """Изменение выбора расширений."""
        self._update_settings_summary()
        self._update_navigation()

    def _update_dest_folder(self) -> None:
        """Установка папки назначения по умолчанию."""
        if not self._edit_dest.text() and self._edit_folder.text():
            source = self._edit_folder.text()
            date_str = datetime.now().strftime("%Y_%m_%d")
            dest = os.path.join(source, f"Выборка_{date_str}")

            # Уникальное имя при дубликатах
            if os.path.exists(dest):
                counter = 1
                while os.path.exists(f"{dest} ({counter})"):
                    counter += 1
                dest = f"{dest} ({counter})"

            self._edit_dest.setText(dest)

    def _on_browse_dest(self) -> None:
        """Выбор папки назначения."""
        current = self._edit_dest.text() or self._edit_folder.text() or ""
        folder = QFileDialog.getExistingDirectory(
            self, "Папка назначения", current
        )
        if folder:
            self._edit_dest.setText(folder)

    def _update_settings_summary(self) -> None:
        """Обновление итоговой информации."""
        selected_exts = self._get_selected_extensions()

        if not self._last_match_result or not selected_exts:
            self._lbl_settings_summary.setText("")
            return

        # Пересчёт с учётом выбранных расширений
        if self._matcher:
            result = self._matcher.find_matches(
                self._get_patterns(), selected_exts
            )
            file_count = result.matched_count
            total_size = result.total_size
        else:
            file_count = 0
            total_size = 0

        mode = "скопировано" if self._cmb_mode.currentIndex() == 0 else "перемещено"
        self._lbl_settings_summary.setText(
            f"Будет {mode}: {file_count} файлов "
            f"({format_file_size(total_size)})"
        )

    # ------------------------------------------------------------------
    # Page 3: Progress
    # ------------------------------------------------------------------

    def _on_execute(self) -> None:
        """Запуск операции."""
        if not self._matcher:
            return

        selected_exts = self._get_selected_extensions()
        if not selected_exts:
            QMessageBox.warning(self, "Внимание", "Выберите хотя бы одно расширение")
            return

        dest_folder = self._edit_dest.text()
        if not dest_folder:
            QMessageBox.warning(self, "Внимание", "Укажите папку назначения")
            return

        # Финальный match с выбранными расширениями
        patterns = self._get_patterns()
        result = self._matcher.find_matches(patterns, selected_exts)

        if result.matched_count == 0:
            QMessageBox.information(self, "Информация", "Нет файлов для обработки")
            return

        # Переход на страницу прогресса
        self._stack.setCurrentIndex(3)
        self._update_navigation()

        # Подготовка UI
        self._progress_bar.setValue(0)
        self._log_text.clear()
        self._btn_open_folder.setVisible(False)
        self._btn_cancel_task.setVisible(True)
        self._btn_close.setVisible(False)

        mode = (
            FileSelectionTask.MODE_COPY
            if self._cmb_mode.currentIndex() == 0
            else FileSelectionTask.MODE_MOVE
        )

        # Сохранение настроек
        self._settings.setValue(_SK_MODE, self._cmb_mode.currentIndex())
        self._settings.setValue(_SK_EXT_FOLDERS, self._chk_ext_folders.isChecked())

        # Запуск задачи
        self._task_signals = FileSelectionTaskSignals()
        self._task_signals.log_message.connect(self._on_task_log)
        self._task_signals.task_completed.connect(self._on_task_completed)
        self._task_signals.task_failed.connect(self._on_task_failed)
        self._task_signals.task_canceled.connect(self._on_task_canceled)

        self._task = FileSelectionTask(
            matched_files=result.matched,
            dest_folder=dest_folder,
            mode=mode,
            create_ext_folders=self._chk_ext_folders.isChecked(),
            source_folder=self._matcher.folder,
            signals=self._task_signals,
        )

        self._task.progressChanged.connect(self._on_task_progress)
        QgsApplication.taskManager().addTask(self._task)

        mode_label = "Копирование" if mode == FileSelectionTask.MODE_COPY else "Перемещение"
        self._log_text.append(
            f"{mode_label} {result.matched_count} файлов -> {dest_folder}\n"
        )
        log_info(f"Fsm_6_4_1: Запущена задача ({mode_label}, {result.matched_count} файлов)")

    def _on_task_log(self, message: str) -> None:
        """Сообщение из задачи."""
        self._log_text.append(message)

    def _on_task_progress(self, progress: float) -> None:
        """Прогресс задачи."""
        self._progress_bar.setValue(int(progress))

    def _on_task_completed(self, results: dict) -> None:
        """Задача завершена успешно."""
        self._log_text.append(
            f"\n--- Завершено ---\n"
            f"Успешно: {results.get('success', 0)}\n"
            f"Пропущено: {results.get('skipped', 0)}\n"
            f"Ошибок: {len(results.get('errors', []))}\n"
            f"Размер: {format_file_size(results.get('total_size', 0))}"
        )

        report_path = results.get('report_path', '')
        if report_path:
            self._log_text.append(f"\nОтчёт: {report_path}")

        self._btn_open_folder.setVisible(True)
        self._btn_cancel_task.setVisible(False)
        self._btn_close.setVisible(True)
        self._task = None

    def _on_task_failed(self, error: str) -> None:
        """Задача завершена с ошибкой."""
        self._log_text.append(f"\nОШИБКА: {error}")
        self._btn_cancel_task.setVisible(False)
        self._btn_close.setVisible(True)
        self._task = None

    def _on_task_canceled(self) -> None:
        """Задача отменена."""
        self._log_text.append("\nОперация отменена пользователем.")
        self._btn_cancel_task.setVisible(False)
        self._btn_close.setVisible(True)
        self._task = None

    def _on_cancel_task(self) -> None:
        """Отмена выполняющейся задачи."""
        if self._task:
            self._task.cancel()

    def _on_open_dest_folder(self) -> None:
        """Открытие папки назначения в проводнике."""
        dest = self._edit_dest.text()
        if dest and os.path.isdir(dest):
            os.startfile(dest)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_patterns(self) -> List[str]:
        """Получение списка паттернов из текстового поля."""
        text = self._edit_list.toPlainText()
        return [line.strip() for line in text.split('\n') if line.strip()]

    def _get_selected_extensions(self) -> Set[str]:
        """Получение выбранных расширений."""
        return {
            ext for ext, cb in self._ext_checkboxes.items()
            if cb.isChecked()
        }

    def _restore_settings(self) -> None:
        """Восстановление настроек из QSettings."""
        subdirs = self._settings.value(_SK_SUBDIRS, False, type=bool)
        self._chk_subdirs.setChecked(subdirs)

        mode_idx = self._settings.value(_SK_MODE, 0, type=int)
        self._cmb_mode.setCurrentIndex(mode_idx)

        ext_folders = self._settings.value(_SK_EXT_FOLDERS, False, type=bool)
        self._chk_ext_folders.setChecked(ext_folders)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Обработка закрытия окна."""
        if self._task and not self._task.isCanceled():
            reply = QMessageBox.question(
                self, "Подтверждение",
                "Операция выполняется. Отменить и закрыть?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
            self._task.cancel()

        super().closeEvent(event)
