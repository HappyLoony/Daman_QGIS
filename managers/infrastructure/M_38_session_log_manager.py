# -*- coding: utf-8 -*-
"""
M_38_SessionLogManager - Менеджер файлового логирования сессий.

Обеспечивает:
- Запись всех QgsMessageLog сообщений в файл (crash-safe)
- Ротацию логов: хранение только 3 последних сессий
- faulthandler для перехвата C-level crashes (segfault)
- Сбор логов для отправки через feedback (F_4_4)

Хранилище: QgsApplication.qgisSettingsDirPath() / "daman_logs/"
Формат файлов: session_YYYY-MM-DD_HH-MM-SS.log
"""

__all__ = ['SessionLogManager']

import os
import logging
import faulthandler
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from qgis.core import QgsApplication, Qgis


class SessionLogManager:
    """
    Менеджер файлового логирования сессий.

    Singleton через registry (M_38). Инициализируется первым в initGui().
    """

    LOG_DIR_NAME = "daman_logs"
    MAX_SESSIONS = 3
    SESSION_PREFIX = "session_"
    CRASH_FILE = "crash_trace.log"

    # Маппинг Qgis.MessageLevel -> строковый уровень
    _LEVEL_MAP = {
        Qgis.Info: "INFO",
        Qgis.Warning: "WARNING",
        Qgis.Critical: "CRITICAL",
        Qgis.Success: "SUCCESS",
        Qgis.NoLevel: "DEBUG",
    }

    def __init__(self):
        self._log_dir: Optional[Path] = None
        self._session_id: Optional[str] = None
        self._log_file: Optional[Path] = None
        self._logger: Optional[logging.Logger] = None
        self._file_handler: Optional[logging.FileHandler] = None
        self._crash_file_handle = None
        self._initialized: bool = False
        self._lock = threading.Lock()
        self._message_log_connected: bool = False

    def initialize(self) -> bool:
        """
        Инициализация системы логирования.

        1. Создаёт папку логов
        2. Ротация: удаляет старые сессии (оставляет MAX_SESSIONS - 1)
        3. Создаёт лог-файл текущей сессии
        4. Подключает faulthandler для segfault
        5. Подключает QgsMessageLog.messageReceived

        Returns:
            True если инициализация успешна
        """
        if self._initialized:
            return True

        try:
            # 1. Определяем путь к папке логов
            settings_dir = QgsApplication.qgisSettingsDirPath()
            self._log_dir = Path(settings_dir) / self.LOG_DIR_NAME
            self._log_dir.mkdir(parents=True, exist_ok=True)

            # 2. Ротация старых сессий
            self._rotate_sessions()

            # 3. Создаём лог-файл текущей сессии
            self._session_id = f"{self.SESSION_PREFIX}{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
            self._log_file = self._log_dir / f"{self._session_id}.log"

            # 4. Настраиваем Python logging
            self._setup_logger()

            # 5. Включаем faulthandler для C-level crashes
            self._setup_faulthandler()

            # 6. Подключаем перехват QgsMessageLog
            self._connect_message_log()

            self._initialized = True

            # Первая запись в лог
            self.write(
                f"M_38: Session log started: {self._session_id}",
                tag="Daman_QGIS", level="INFO"
            )

            return True

        except Exception as e:
            # Не используем log_error (может быть ещё не доступен)
            try:
                from Daman_QGIS.utils import log_warning
                log_warning(f"M_38: Failed to initialize session logging: {e}")
            except ImportError:
                pass
            return False

    def write(self, message: str, tag: str = "", level: str = "INFO") -> None:
        """
        Записать сообщение в лог-файл.

        Thread-safe. Каждое сообщение записывается немедленно (flush).

        Args:
            message: Текст сообщения
            tag: Источник сообщения (имя плагина/модуля)
            level: Уровень логирования (INFO, WARNING, CRITICAL, SUCCESS, DEBUG)
        """
        if not self._initialized or self._logger is None:
            return

        with self._lock:
            try:
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                tag_str = f" [{tag}]" if tag else ""
                formatted = f"{timestamp} [{level}]{tag_str} {message}"

                # Используем logging для записи (автоматический flush через handler)
                self._logger.info(formatted)

                # Принудительный flush для crash-safety
                if self._file_handler:
                    self._file_handler.flush()

            except Exception:
                pass  # Не ломаем основной код при ошибках записи

    def get_session_logs(self, max_lines: int = 500) -> List[Dict[str, str]]:
        """
        Получить логи последних сессий для отправки через feedback.

        Читает все session_*.log файлы в папке (до MAX_SESSIONS).
        Для каждого файла берёт последние max_lines строк.

        Args:
            max_lines: Максимум строк из каждого файла

        Returns:
            Список словарей: [{"session_id": "...", "content": "..."}, ...]
        """
        import time as _time
        t0 = _time.time()

        if not self._log_dir or not self._log_dir.exists():
            self.write("M_38: get_session_logs: log_dir не существует", level="WARNING")
            return []

        # Принудительный flush текущей сессии перед чтением
        if self._file_handler:
            try:
                self._file_handler.flush()
            except Exception:
                pass

        result = []
        session_files = sorted(
            self._log_dir.glob(f"{self.SESSION_PREFIX}*.log"),
            reverse=True  # Новейшие первыми
        )
        self.write(
            f"M_38: get_session_logs: найдено {len(session_files)} файлов, "
            f"читаем до {self.MAX_SESSIONS}, max_lines={max_lines}",
            level="INFO"
        )

        for log_file in session_files[:self.MAX_SESSIONS]:
            try:
                tf0 = _time.time()
                session_id = log_file.stem
                file_size = log_file.stat().st_size
                content = self._read_last_lines(log_file, max_lines)
                tf1 = _time.time()
                self.write(
                    f"M_38: get_session_logs: прочитан {session_id} "
                    f"({file_size / 1024:.0f} KB, {len(content)} chars, {tf1 - tf0:.3f}s)",
                    level="INFO"
                )
                result.append({
                    "session_id": session_id,
                    "content": content
                })
            except Exception as e:
                self.write(
                    f"M_38: get_session_logs: ошибка чтения {log_file.name}: "
                    f"{type(e).__name__}: {e}",
                    level="WARNING"
                )
                continue

        # Добавляем crash_trace.log если он есть и не пустой
        crash_file = self._log_dir / self.CRASH_FILE
        if crash_file.exists() and crash_file.stat().st_size > 0:
            try:
                crash_content = self._read_last_lines(crash_file, 100)
                if crash_content.strip():
                    result.append({
                        "session_id": "crash_trace",
                        "content": crash_content
                    })
                    self.write("M_38: get_session_logs: crash_trace.log добавлен", level="INFO")
            except Exception:
                pass

        t1 = _time.time()
        total_chars = sum(len(r.get("content", "")) for r in result)
        self.write(
            f"M_38: get_session_logs ЗАВЕРШЕН: {len(result)} записей, "
            f"{total_chars / 1024:.0f} KB, за {t1 - t0:.3f}s",
            level="INFO"
        )

        return result

    def get_log_dir(self) -> Optional[Path]:
        """Путь к папке логов."""
        return self._log_dir

    def get_session_id(self) -> Optional[str]:
        """ID текущей сессии."""
        return self._session_id

    def shutdown(self) -> None:
        """
        Корректное завершение: flush, close handlers, disable faulthandler.

        Вызывается из main_plugin.unload().
        """
        if not self._initialized:
            return

        try:
            self.write(
                "M_38: Session log shutdown",
                tag="Daman_QGIS", level="INFO"
            )
        except Exception:
            pass

        # Отключаем QgsMessageLog
        self._disconnect_message_log()

        # Закрываем file handler
        if self._file_handler:
            try:
                self._file_handler.flush()
                self._file_handler.close()
            except Exception:
                pass
            self._file_handler = None

        # Отключаем faulthandler
        try:
            faulthandler.disable()
        except Exception:
            pass

        # Закрываем файл crash_trace
        if self._crash_file_handle:
            try:
                self._crash_file_handle.close()
            except Exception:
                pass
            self._crash_file_handle = None

        # Удаляем logger
        if self._logger:
            try:
                for handler in self._logger.handlers[:]:
                    self._logger.removeHandler(handler)
            except Exception:
                pass
            self._logger = None

        self._initialized = False

    # ========================================================================
    # PRIVATE METHODS
    # ========================================================================

    def _rotate_sessions(self) -> None:
        """Удалить старые сессии, оставив MAX_SESSIONS - 1 (текущая будет создана)."""
        if not self._log_dir:
            return

        session_files = sorted(self._log_dir.glob(f"{self.SESSION_PREFIX}*.log"))

        # Оставляем MAX_SESSIONS - 1 = 2 файла (3-й = текущая сессия)
        files_to_keep = self.MAX_SESSIONS - 1
        files_to_delete = session_files[:-files_to_keep] if len(session_files) > files_to_keep else []

        for old_file in files_to_delete:
            try:
                old_file.unlink()
            except Exception:
                pass  # Файл может быть заблокирован другим процессом

    def _setup_logger(self) -> None:
        """Настроить Python logging с FileHandler."""
        # Используем уникальное имя логгера для избежания конфликтов
        logger_name = f"daman_session_{os.getpid()}"
        self._logger = logging.getLogger(logger_name)
        self._logger.setLevel(logging.DEBUG)

        # Убираем все существующие handlers (на случай повторной инициализации)
        for handler in self._logger.handlers[:]:
            self._logger.removeHandler(handler)

        # FileHandler: пишет каждое сообщение сразу
        self._file_handler = logging.FileHandler(
            str(self._log_file),
            mode='a',
            encoding='utf-8'
        )
        # Формат минимальный — основное форматирование в write()
        self._file_handler.setFormatter(logging.Formatter('%(message)s'))
        self._file_handler.setLevel(logging.DEBUG)

        self._logger.addHandler(self._file_handler)

        # Отключаем propagation чтобы не дублировать в root logger
        self._logger.propagate = False

    def _setup_faulthandler(self) -> None:
        """Включить faulthandler для перехвата segfault."""
        if not self._log_dir:
            return

        try:
            crash_file = self._log_dir / self.CRASH_FILE
            # Открываем файл для записи (перезаписываем каждую сессию)
            self._crash_file_handle = open(crash_file, 'w', encoding='utf-8')

            # Записываем заголовок
            self._crash_file_handle.write(
                f"Crash trace for session: {self._session_id}\n"
                f"Started: {datetime.now().isoformat()}\n"
                f"---\n"
            )
            self._crash_file_handle.flush()

            # Включаем faulthandler — запишет traceback при segfault
            faulthandler.enable(file=self._crash_file_handle, all_threads=True)

        except Exception:
            pass  # faulthandler опционален, не критичен

    def _connect_message_log(self) -> None:
        """Подключить перехват QgsMessageLog.messageReceived."""
        try:
            msg_log = QgsApplication.messageLog()
            if msg_log:
                msg_log.messageReceived.connect(self._on_message_received)
                self._message_log_connected = True
        except Exception:
            pass

    def _disconnect_message_log(self) -> None:
        """Отключить перехват QgsMessageLog."""
        if not self._message_log_connected:
            return

        try:
            msg_log = QgsApplication.messageLog()
            if msg_log:
                msg_log.messageReceived.disconnect(self._on_message_received)
        except (TypeError, RuntimeError):
            pass  # Уже отключен или объект уничтожен

        self._message_log_connected = False

    def _on_message_received(self, message: str, tag: str, level) -> None:
        """
        Обработчик сигнала QgsMessageLog.messageReceived.

        Перехватывает ВСЕ сообщения QGIS (включая другие плагины, GDAL и т.д.).
        Сообщения от Daman_QGIS пропускаются — они уже записаны через utils.py.

        Args:
            message: Текст сообщения
            tag: Источник (имя плагина)
            level: Qgis.MessageLevel
        """
        # Пропускаем сообщения от нашего плагина — они уже записаны
        # через _write_to_session_log в utils.py
        from Daman_QGIS.constants import PLUGIN_NAME
        if tag == PLUGIN_NAME:
            return

        level_str = self._LEVEL_MAP.get(level, "UNKNOWN")
        self.write(message, tag=tag, level=level_str)

    def _read_last_lines(self, file_path: Path, max_lines: int) -> str:
        """
        Прочитать последние max_lines строк из файла.

        Args:
            file_path: Путь к файлу
            max_lines: Максимум строк

        Returns:
            Строка с последними строками файла
        """
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # Берём последние max_lines строк
            if len(lines) > max_lines:
                lines = lines[-max_lines:]

            return ''.join(lines)
        except Exception:
            return ""
