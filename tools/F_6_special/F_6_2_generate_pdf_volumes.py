# -*- coding: utf-8 -*-
"""
F_6_2: Сформировать тома PDF.

Конвертация файлов проекта (DWG, DOCX, XLSX) из папки "Выпуск новый"
в PDF с формированием итоговых томов.

Этапы:
1. Обнаружение файлов в Редактируемый формат/
2. Конвертация через COM (Word, Excel, AutoCAD) -> _pdf рабочие/
3. Объединение PDF по томам -> pdf/

Выходные папки получаются через M_19 (FolderType.DPT_PDF_DRAFT,
FolderType.DPT_PDF) внутри текущего открытого QGIS-проекта.
"""

import os
import glob
from typing import Optional, List, Dict, Tuple

from qgis.PyQt.QtCore import pyqtSignal, QObject
from qgis.core import QgsTask, QgsApplication, QgsProject

from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.managers import registry
from Daman_QGIS.managers.core.M_19_project_structure_manager import FolderType

from .submodules.Fsm_6_2_1_dialog import Fsm_6_2_1_Dialog
from .submodules.Fsm_6_2_2_converter import (
    FileType, ConversionResult, convert_files
)
from .submodules.Fsm_6_2_3_merger import PdfVolumeMerger


class PdfVolumeTaskSignals(QObject):
    """Сигналы для связи между QgsTask и UI."""
    log_message = pyqtSignal(str)
    task_completed = pyqtSignal(int, int, list)  # success, total, output_files
    task_failed = pyqtSignal(str)
    task_canceled = pyqtSignal()


class PdfVolumeTask(QgsTask):
    """
    Фоновая задача формирования томов PDF.

    Выполняет конвертацию и объединение в отдельном потоке.
    """

    def __init__(
        self,
        source_folder: str,
        signals: PdfVolumeTaskSignals
    ):
        super().__init__("Формирование томов PDF", QgsTask.CanCancel)
        self.source_folder = source_folder
        self.signals = signals
        self.error_message: Optional[str] = None

        # Обнаруженные файлы
        self.dwg_files: List[str] = []
        self.volume_files: Dict[str, List[Tuple[str, FileType]]] = {}

        # Выходные директории через M_19 (внутри текущего проекта QGIS)
        structure_manager = registry.get('M_19')
        if not structure_manager.is_active():
            project_path = QgsProject.instance().homePath()
            if project_path:
                structure_manager.project_root = os.path.normpath(project_path)

        self.working_dir: Optional[str] = structure_manager.get_folder(
            FolderType.DPT_PDF_DRAFT
        )
        self.output_dir: Optional[str] = structure_manager.get_folder(
            FolderType.DPT_PDF
        )

        # Результаты
        self.output_files: List[str] = []

    def run(self) -> bool:
        """Выполнить формирование PDF в фоновом потоке."""
        try:
            # Инициализация COM для worker-потока
            import comtypes
            comtypes.CoInitialize()

            try:
                return self._do_work()
            finally:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass

        except ImportError:
            self.error_message = (
                "Библиотека comtypes не установлена. "
                "Установите через F_4_1 Проверка зависимостей."
            )
            log_error(f"F_6_2: {self.error_message}")
            return False
        except Exception as e:
            self.error_message = str(e)
            log_error(f"F_6_2: Ошибка в фоновой задаче: {e}")
            return False

    def _do_work(self) -> bool:
        """Основная логика обработки."""
        # Проверка что M_19 вернул валидные пути (проект QGIS открыт)
        if not self.working_dir or not self.output_dir:
            self.error_message = (
                "F_6_2: Проект QGIS не открыт. "
                "Сохраните проект перед формированием томов."
            )
            log_error(self.error_message)
            return False

        # === Фаза 1: Обнаружение файлов (0-5%) ===
        self.signals.log_message.emit(
            "=== Фаза 1: Обнаружение файлов ===\n"
        )
        self.setProgress(0)

        self._discover_files()

        total_files = (
            len(self.dwg_files) +
            sum(len(v) for v in self.volume_files.values())
        )

        if total_files == 0:
            self.signals.log_message.emit("Файлы для конвертации не найдены.")
            return True

        self.signals.log_message.emit(
            f"DWG: {len(self.dwg_files)}, "
            f"Томов: {len(self.volume_files)}, "
            f"Всего файлов: {total_files}\n"
        )
        self.setProgress(5)

        if self.isCanceled():
            return False

        # === Фаза 2: Конвертация (5-80%) ===
        self.signals.log_message.emit(
            "=== Фаза 2: Конвертация файлов в PDF ===\n"
        )

        # Создать выходные директории
        os.makedirs(self.working_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

        # Подготовить список файлов для конвертации
        conversion_map = self._build_conversion_map()

        results = convert_files(
            files=conversion_map,
            progress_callback=self._on_conversion_progress,
            cancel_check=self.isCanceled
        )

        # Отчет по конвертации
        success_count = sum(1 for r in results if r.success)
        fail_count = sum(1 for r in results if not r.success)

        self.signals.log_message.emit(
            f"\nКонвертировано: {success_count}/{len(results)}"
        )
        if fail_count > 0:
            self.signals.log_message.emit(f"Ошибок: {fail_count}")
            for r in results:
                if not r.success:
                    self.signals.log_message.emit(
                        f"  - {os.path.basename(r.input_path)}: {r.error}"
                    )
        self.signals.log_message.emit("")

        self.setProgress(80)

        if self.isCanceled():
            return False

        # === Фаза 3: Объединение PDF (80-95%) ===
        self.signals.log_message.emit(
            "=== Фаза 3: Объединение PDF в тома ===\n"
        )

        try:
            merger = PdfVolumeMerger()
            merge_results = merger.process_all_volumes(
                self.working_dir,
                self.output_dir,
                progress_callback=self._on_merge_progress
            )

            for path, success in merge_results:
                if success:
                    self.output_files.append(path)
                    self.signals.log_message.emit(
                        f"  {os.path.basename(path)}"
                    )
                else:
                    self.signals.log_message.emit(
                        f"  ОШИБКА: {os.path.basename(path)}"
                    )

        except ImportError:
            self.signals.log_message.emit(
                "Библиотека pypdf не установлена. "
                "Установите через F_4_1."
            )
            log_error("F_6_2: pypdf не установлена")

        self.setProgress(95)

        # === Фаза 4: Отчет (95-100%) ===
        self.signals.log_message.emit(
            f"\n=== Готово ===\n"
            f"Создано итоговых файлов: {len(self.output_files)}\n"
            f"_pdf рабочие: {self.working_dir}\n"
            f"pdf: {self.output_dir}\n"
        )
        self.setProgress(100)

        return True

    def _discover_files(self) -> None:
        """Обнаружить файлы для конвертации."""
        edit_fmt = os.path.join(
            self.source_folder, "Редактируемый формат"
        )

        # DWG файлы
        graphics_dir = os.path.join(edit_fmt, "Графическая часть")
        if os.path.isdir(graphics_dir):
            self.dwg_files = sorted(
                glob.glob(os.path.join(graphics_dir, "*.dwg"))
            )
            if self.dwg_files:
                self.signals.log_message.emit(
                    f"Графическая часть: {len(self.dwg_files)} DWG"
                )

        # DOCX/XLSX по томам
        text_dir = os.path.join(edit_fmt, "Текстовая часть")
        if os.path.isdir(text_dir):
            for entry in sorted(os.listdir(text_dir)):
                vol_dir = os.path.join(text_dir, entry)
                if not os.path.isdir(vol_dir):
                    continue

                files: List[Tuple[str, FileType]] = []
                for f in sorted(os.listdir(vol_dir)):
                    if f.startswith("~$"):
                        continue
                    fp = os.path.join(vol_dir, f)
                    ext = os.path.splitext(f)[1].lower()
                    if ext == ".docx":
                        files.append((fp, FileType.DOCX))
                    elif ext == ".xlsx":
                        files.append((fp, FileType.XLSX))

                if files:
                    self.volume_files[entry] = files
                    docx_n = sum(1 for _, t in files if t == FileType.DOCX)
                    xlsx_n = sum(1 for _, t in files if t == FileType.XLSX)
                    self.signals.log_message.emit(
                        f"{entry}: {docx_n} DOCX, {xlsx_n} XLSX"
                    )

    def _build_conversion_map(
        self
    ) -> Dict[FileType, List[Tuple[str, str]]]:
        """Построить маппинг файлов для конвертации."""
        result: Dict[FileType, List[Tuple[str, str]]] = {
            FileType.DOCX: [],
            FileType.XLSX: [],
            FileType.DWG: [],
        }

        # DWG -> _pdf рабочие/Графика/
        graphics_out = os.path.join(self.working_dir, "Графика")
        for dwg_path in self.dwg_files:
            name = os.path.splitext(os.path.basename(dwg_path))[0]
            out_path = os.path.join(graphics_out, f"{name}.pdf")
            result[FileType.DWG].append((dwg_path, out_path))

        # DOCX/XLSX -> _pdf рабочие/Том N/
        for volume_name, files in self.volume_files.items():
            vol_out = os.path.join(self.working_dir, volume_name)
            for file_path, file_type in files:
                name = os.path.splitext(os.path.basename(file_path))[0]
                out_path = os.path.join(vol_out, f"{name}.pdf")
                result[file_type].append((file_path, out_path))

        return result

    def _on_conversion_progress(
        self, filename: str, current: int, total: int
    ) -> None:
        """Обработчик прогресса конвертации."""
        self.signals.log_message.emit(
            f"  [{current}/{total}] {filename}"
        )
        # Прогресс: 5% -> 80% (75% диапазон)
        progress = 5 + int(75 * current / max(total, 1))
        self.setProgress(progress)

    def _on_merge_progress(
        self, volume_name: str, current: int, total: int
    ) -> None:
        """Обработчик прогресса объединения."""
        # Прогресс: 80% -> 95% (15% диапазон)
        progress = 80 + int(15 * current / max(total, 1))
        self.setProgress(progress)

    def finished(self, result: bool) -> None:
        """Вызывается при завершении задачи (в главном потоке)."""
        if self.isCanceled():
            self.signals.task_canceled.emit()
        elif result:
            total = (
                len(self.dwg_files) +
                sum(len(v) for v in self.volume_files.values())
            )
            self.signals.task_completed.emit(
                len(self.output_files), total, self.output_files
            )
        else:
            self.signals.task_failed.emit(
                self.error_message or "Неизвестная ошибка"
            )


class F_6_2_GeneratePdfVolumes(BaseTool):
    """Сформировать тома PDF из DWG/DOCX/XLSX."""

    def __init__(self, iface):
        super().__init__(iface)
        self.dialog: Optional[Fsm_6_2_1_Dialog] = None
        self._task: Optional[PdfVolumeTask] = None
        self._task_signals: Optional[PdfVolumeTaskSignals] = None

    def run(self) -> None:
        """Запуск функции."""
        log_info("F_6_2: Запуск функции Сформировать тома PDF")

        # Проверка зависимостей
        if not self._check_dependencies():
            return

        self.dialog = Fsm_6_2_1_Dialog(self.iface.mainWindow())
        self.dialog.set_run_callback(self._on_process)
        self.dialog.exec()

    def _check_dependencies(self) -> bool:
        """Проверить наличие comtypes и pypdf."""
        missing = []
        try:
            import comtypes  # noqa: F401
        except ImportError:
            missing.append("comtypes")

        try:
            import pypdf  # noqa: F401
        except ImportError:
            missing.append("pypdf")

        if missing:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Отсутствуют зависимости",
                f"Не установлены библиотеки: {', '.join(missing)}.\n\n"
                "Установите через меню:\n"
                "Daman QGIS -> Плагин -> Проверка зависимостей (F_4_1)"
            )
            log_warning(f"F_6_2: Отсутствуют зависимости: {missing}")
            return False

        return True

    def _on_process(self, source_folder: str) -> None:
        """Обработчик кнопки Сформировать."""
        log_info(f"F_6_2: Начало обработки. Источник: {source_folder}")

        if not self.dialog:
            return

        # Проверить наличие папок в источнике
        edit_fmt = os.path.join(source_folder, "Редактируемый формат")
        if not os.path.isdir(edit_fmt):
            self.dialog.append_log(
                "Папка 'Редактируемый формат' не найдена!"
            )
            return

        self.dialog.set_controls_enabled(False)
        self.dialog.show_progress(True)
        self.dialog.clear_log()

        # Создать сигналы
        self._task_signals = PdfVolumeTaskSignals()
        self._task_signals.log_message.connect(self._on_task_log)
        self._task_signals.task_completed.connect(self._on_task_completed)
        self._task_signals.task_failed.connect(self._on_task_failed)
        self._task_signals.task_canceled.connect(self._on_task_canceled)

        # Создать и запустить задачу
        self._task = PdfVolumeTask(
            source_folder=source_folder,
            signals=self._task_signals
        )

        if self.dialog:
            self.dialog.set_task_reference(self._task)

        self._task.progressChanged.connect(self._on_task_progress)
        QgsApplication.taskManager().addTask(self._task)
        log_info("F_6_2: Фоновая задача запущена")

    def _on_task_log(self, message: str) -> None:
        """Обработчик сообщений из задачи."""
        if self.dialog:
            self.dialog.append_log(message)

    def _on_task_progress(self, progress: float) -> None:
        """Обработчик прогресса."""
        if self.dialog:
            self.dialog.set_progress(int(progress), 100)

    def _on_task_completed(
        self, success_count: int, total_count: int,
        output_files: List[str]
    ) -> None:
        """Обработчик успешного завершения."""
        log_info(
            f"F_6_2: Задача завершена. "
            f"Создано: {success_count}, всего файлов: {total_count}"
        )
        if self.dialog:
            self.dialog.set_controls_enabled(True)
            self.dialog.show_progress(False)
            self.dialog.append_log(
                f"\nЗадача завершена успешно. "
                f"Создано файлов: {success_count}"
            )

    def _on_task_failed(self, error: str) -> None:
        """Обработчик ошибки."""
        log_error(f"F_6_2: Задача завершена с ошибкой: {error}")
        if self.dialog:
            self.dialog.set_controls_enabled(True)
            self.dialog.show_progress(False)
            self.dialog.append_log(f"\nОШИБКА: {error}")

    def _on_task_canceled(self) -> None:
        """Обработчик отмены."""
        log_info("F_6_2: Задача отменена пользователем")
        if self.dialog:
            self.dialog.set_controls_enabled(True)
            self.dialog.show_progress(False)
            self.dialog.append_log("\nЗадача отменена.")
