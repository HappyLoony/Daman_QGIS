# -*- coding: utf-8 -*-
"""
Fsm_6_2_2: Конвертация DWG/DOCX/XLSX в PDF через COM automation.

Использует comtypes для управления Word, Excel и AutoCAD
через Windows COM интерфейсы.

Каждый конвертер создает один экземпляр COM-приложения
и переиспользует его для всех файлов данного типа.
"""

import gc
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable, Dict, List, Tuple

from Daman_QGIS.utils import log_info, log_error, log_warning


class FileType(Enum):
    """Типы файлов для конвертации."""
    DWG = "dwg"
    DOCX = "docx"
    XLSX = "xlsx"


@dataclass
class ConversionResult:
    """Результат конвертации одного файла."""
    success: bool
    input_path: str
    output_path: Optional[str]
    error: Optional[str]
    duration_ms: int


class BaseComConverter(ABC):
    """Базовый класс COM-конвертера."""

    def __init__(self):
        self._app = None
        self._initialized = False
        self._was_running = False

    @abstractmethod
    def initialize(self) -> bool:
        """Инициализировать COM-приложение. Вернуть True при успехе."""

    @abstractmethod
    def _do_convert(self, input_path: str, output_path: str) -> None:
        """Выполнить конвертацию (реализация в подклассе)."""

    @abstractmethod
    def shutdown(self) -> None:
        """Закрыть COM-приложение."""

    @property
    def app_name(self) -> str:
        """Название приложения для логов."""
        return self.__class__.__name__

    def convert(self, input_path: str, output_path: str) -> ConversionResult:
        """Конвертировать один файл в PDF."""
        start_time = time.time()
        try:
            if not self._initialized:
                return ConversionResult(
                    success=False,
                    input_path=input_path,
                    output_path=None,
                    error=f"{self.app_name} не инициализирован",
                    duration_ms=0
                )

            # Создать директорию для выходного файла
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            self._do_convert(input_path, output_path)

            duration_ms = int((time.time() - start_time) * 1000)

            if os.path.exists(output_path):
                log_info(
                    f"Fsm_6_2_2 ({self.app_name}): "
                    f"OK {os.path.basename(input_path)} ({duration_ms} ms)"
                )
                return ConversionResult(
                    success=True,
                    input_path=input_path,
                    output_path=output_path,
                    error=None,
                    duration_ms=duration_ms
                )
            else:
                return ConversionResult(
                    success=False,
                    input_path=input_path,
                    output_path=None,
                    error="Выходной файл не создан",
                    duration_ms=int((time.time() - start_time) * 1000)
                )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            log_error(
                f"Fsm_6_2_2 ({self.app_name}): "
                f"Ошибка конвертации {os.path.basename(input_path)}: {e}"
            )
            return ConversionResult(
                success=False,
                input_path=input_path,
                output_path=None,
                error=str(e),
                duration_ms=duration_ms
            )

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, *args):
        self.shutdown()


class WordConverter(BaseComConverter):
    """Конвертация DOCX в PDF через Microsoft Word COM."""

    WD_FORMAT_PDF = 17
    WD_ALERTS_NONE = 0

    @property
    def app_name(self) -> str:
        return "Word"

    def initialize(self) -> bool:
        """Подключиться к запущенному Word или запустить новый."""
        try:
            import comtypes.client

            # Попробовать подключиться к запущенному Word
            try:
                self._app = comtypes.client.GetActiveObject("Word.Application")
                self._was_running = True
                log_info("Fsm_6_2_2 (Word): Подключен к запущенному")
            except Exception:
                self._app = comtypes.client.CreateObject("Word.Application")
                self._was_running = False
                log_info("Fsm_6_2_2 (Word): Запущен новый экземпляр")

            self._app.Visible = False
            self._app.DisplayAlerts = self.WD_ALERTS_NONE
            self._initialized = True
            return True
        except Exception as e:
            log_error(f"Fsm_6_2_2 (Word): Не удалось запустить Word: {e}")
            self._initialized = False
            return False

    def _do_convert(self, input_path: str, output_path: str) -> None:
        """Конвертировать DOCX в PDF."""
        doc = None
        try:
            doc = self._app.Documents.Open(
                os.path.abspath(input_path),
                ReadOnly=True
            )
            doc.SaveAs(
                os.path.abspath(output_path),
                FileFormat=self.WD_FORMAT_PDF
            )
        finally:
            if doc is not None:
                try:
                    doc.Close(SaveChanges=0)
                except Exception:
                    pass

    def shutdown(self) -> None:
        """Закрыть Word (только если запущен нами)."""
        if self._app is not None:
            if not self._was_running:
                try:
                    self._app.Quit()
                    log_info("Fsm_6_2_2 (Word): COM закрыт")
                except Exception as e:
                    log_warning(
                        f"Fsm_6_2_2 (Word): Ошибка при закрытии: {e}"
                    )
            else:
                log_info(
                    "Fsm_6_2_2 (Word): Оставлен запущенным "
                    "(был открыт до конвертации)"
                )
            del self._app
            self._app = None
            self._initialized = False
            gc.collect()


class ExcelConverter(BaseComConverter):
    """Конвертация XLSX в PDF через Microsoft Excel COM."""

    XL_TYPE_PDF = 0

    @property
    def app_name(self) -> str:
        return "Excel"

    def initialize(self) -> bool:
        """Подключиться к запущенному Excel или запустить новый."""
        try:
            import comtypes.client

            # Попробовать подключиться к запущенному Excel
            try:
                self._app = comtypes.client.GetActiveObject("Excel.Application")
                self._was_running = True
                log_info("Fsm_6_2_2 (Excel): Подключен к запущенному")
            except Exception:
                self._app = comtypes.client.CreateObject("Excel.Application")
                self._was_running = False
                log_info("Fsm_6_2_2 (Excel): Запущен новый экземпляр")

            self._app.Visible = False
            self._app.DisplayAlerts = False
            self._initialized = True
            return True
        except Exception as e:
            log_error(f"Fsm_6_2_2 (Excel): Не удалось запустить Excel: {e}")
            self._initialized = False
            return False

    def _do_convert(self, input_path: str, output_path: str) -> None:
        """Конвертировать XLSX в PDF."""
        wb = None
        try:
            wb = self._app.Workbooks.Open(
                os.path.abspath(input_path),
                ReadOnly=True
            )
            wb.ExportAsFixedFormat(
                Type=self.XL_TYPE_PDF,
                Filename=os.path.abspath(output_path)
            )
        finally:
            if wb is not None:
                try:
                    wb.Close(SaveChanges=False)
                except Exception:
                    pass

    def shutdown(self) -> None:
        """Закрыть Excel (только если запущен нами)."""
        if self._app is not None:
            if not self._was_running:
                try:
                    self._app.Quit()
                    log_info("Fsm_6_2_2 (Excel): COM закрыт")
                except Exception as e:
                    log_warning(
                        f"Fsm_6_2_2 (Excel): Ошибка при закрытии: {e}"
                    )
            else:
                log_info(
                    "Fsm_6_2_2 (Excel): Оставлен запущенным "
                    "(был открыт до конвертации)"
                )
            del self._app
            self._app = None
            self._initialized = False
            gc.collect()


class AutoCADConverter(BaseComConverter):
    """Конвертация DWG в PDF через AutoCAD COM."""

    # ProgID в порядке приоритета (новые версии первыми)
    PROGIDS = [
        "AutoCAD.Application.25",  # AutoCAD 2025
        "AutoCAD.Application.24",  # AutoCAD 2023-2024
        "AutoCAD.Application.23",  # AutoCAD 2021-2022
        "AutoCAD.Application",     # Любая версия
    ]

    # Таймаут ожидания PDF файла (секунды)
    FILE_TIMEOUT = 120
    POLL_INTERVAL = 0.5

    def __init__(self):
        super().__init__()
        self._was_running = False

    @property
    def app_name(self) -> str:
        return "AutoCAD"

    def initialize(self) -> bool:
        """Подключиться к запущенному AutoCAD или запустить новый."""
        import comtypes.client

        # Сначала попробовать подключиться к запущенному
        for progid in self.PROGIDS:
            try:
                self._app = comtypes.client.GetActiveObject(progid)
                self._was_running = True
                self._initialized = True
                log_info(
                    f"Fsm_6_2_2 (AutoCAD): "
                    f"Подключен к запущенному ({progid})"
                )
                return True
            except Exception:
                continue

        # Не найден запущенный - попробовать запустить
        for progid in self.PROGIDS:
            try:
                self._app = comtypes.client.CreateObject(progid)
                self._app.Visible = True
                self._was_running = False
                self._initialized = True
                log_info(
                    f"Fsm_6_2_2 (AutoCAD): Запущен новый экземпляр ({progid})"
                )
                return True
            except Exception:
                continue

        log_error("Fsm_6_2_2 (AutoCAD): Не удалось подключиться к AutoCAD")
        self._initialized = False
        return False

    def _do_convert(self, input_path: str, output_path: str) -> None:
        """Конвертировать DWG в PDF через EXPORTPDF с fallback на PLOT."""
        doc = None
        abs_input = os.path.abspath(input_path)
        abs_output = os.path.abspath(output_path)

        try:
            doc = self._app.Documents.Open(abs_input, True)  # ReadOnly

            # Отключить диалоги файлов
            doc.SendCommand("FILEDIA 0\n")
            time.sleep(0.3)

            # Попытка 1: EXPORTPDF (AutoCAD 2017+)
            export_cmd = f'-EXPORTPDF\n{abs_output}\n'
            doc.SendCommand(export_cmd)

            # Ожидание создания файла
            if not self._wait_for_file(abs_output):
                # Попытка 2: Fallback через -PLOT с "DWG To PDF.pc3"
                log_warning(
                    "Fsm_6_2_2 (AutoCAD): "
                    "EXPORTPDF не сработал, пробуем PLOT"
                )
                plot_cmd = (
                    '-PLOT\n'
                    'Y\n'               # Detailed plot config
                    '\n'                # Current layout
                    'DWG To PDF.pc3\n'  # Plotter
                    '\n'                # Paper size (default)
                    '\n'                # Plot area (default)
                    '\n'                # Plot offset (default)
                    'Y\n'              # Plot to file
                    f'{abs_output}\n'
                    'N\n'              # Save changes? No
                    'Y\n'              # Proceed with plot
                )
                doc.SendCommand(plot_cmd)

                if not self._wait_for_file(abs_output):
                    raise TimeoutError(
                        f"PDF не создан за {self.FILE_TIMEOUT} сек "
                        "(EXPORTPDF и PLOT)"
                    )

        finally:
            if doc is not None:
                try:
                    doc.Close(False)
                except Exception:
                    pass

    def _wait_for_file(self, file_path: str) -> bool:
        """Ожидание создания и стабилизации PDF файла."""
        elapsed = 0.0
        while elapsed < self.FILE_TIMEOUT:
            time.sleep(self.POLL_INTERVAL)
            elapsed += self.POLL_INTERVAL
            if os.path.exists(file_path):
                # Подождать стабилизации размера файла
                size1 = os.path.getsize(file_path)
                time.sleep(0.5)
                size2 = os.path.getsize(file_path)
                if size1 == size2 and size1 > 0:
                    return True
        return False

    def shutdown(self) -> None:
        """Закрыть AutoCAD (только если был запущен нами)."""
        if self._app is not None:
            if not self._was_running:
                try:
                    self._app.Quit()
                    log_info("Fsm_6_2_2 (AutoCAD): COM закрыт")
                except Exception as e:
                    log_warning(
                        f"Fsm_6_2_2 (AutoCAD): Ошибка при закрытии: {e}"
                    )
            else:
                log_info(
                    "Fsm_6_2_2 (AutoCAD): "
                    "Оставлен запущенным (был открыт до конвертации)"
                )
            del self._app
            self._app = None
            self._initialized = False
            gc.collect()


# Маппинг типов файлов на классы конвертеров
CONVERTER_CLASSES: Dict[FileType, type] = {
    FileType.DOCX: WordConverter,
    FileType.XLSX: ExcelConverter,
    FileType.DWG: AutoCADConverter,
}


def convert_files(
    files: Dict[FileType, List[Tuple[str, str]]],
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None
) -> List[ConversionResult]:
    """
    Конвертировать все файлы в PDF.

    Создает один экземпляр COM-приложения на тип файла.
    Одна ошибка не останавливает остальные конвертации.

    Args:
        files: Словарь {FileType: [(input_path, output_path), ...]}
        progress_callback: callback(filename, current, total)
        cancel_check: Функция проверки отмены (вернуть True для отмены)

    Returns:
        Список результатов конвертации
    """
    results: List[ConversionResult] = []
    total = sum(len(v) for v in files.values())
    current = 0

    for file_type, file_pairs in files.items():
        if not file_pairs:
            continue

        if cancel_check and cancel_check():
            break

        converter_class = CONVERTER_CLASSES[file_type]
        converter = converter_class()

        if not converter.initialize():
            # Приложение недоступно - пропустить все файлы этого типа
            for inp, out in file_pairs:
                current += 1
                results.append(ConversionResult(
                    success=False,
                    input_path=inp,
                    output_path=None,
                    error=f"{converter.app_name} не установлен или недоступен",
                    duration_ms=0
                ))
            continue

        try:
            for input_path, output_path in file_pairs:
                if cancel_check and cancel_check():
                    break

                current += 1
                if progress_callback:
                    progress_callback(
                        os.path.basename(input_path), current, total
                    )

                result = converter.convert(input_path, output_path)
                results.append(result)
        finally:
            converter.shutdown()

    return results
