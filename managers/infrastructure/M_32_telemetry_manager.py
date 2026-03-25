# -*- coding: utf-8 -*-
"""
M_32_TelemetryManager - Менеджер телеметрии Daman QGIS.

Отвечает за:
- Сбор событий использования плагина
- Сбор ошибок и исключений
- Батчинг и отправку на сервер
- Санитизацию данных (удаление PII)
- Фильтрацию событий на основе TELEMETRY_LEVEL

Уровни телеметрии (TELEMETRY_LEVEL в constants.py):
- CRITICAL: только ошибки и crashes
- ERROR: ошибки + критические API failures (status >= 400)
- SAMPLING: минимальная статистика (1% success) + все ошибки
- ALL: все события (для отладки)

Типы событий:
- startup: запуск плагина
- function_start/end: вызов функций F_X_Y
- error: некритические ошибки и crashes (через global exception hook)
- api_call: вызовы внешних API

Данные НЕ содержат:
- Пути к файлам пользователя
- Имена проектов
- Координаты
- Содержимое атрибутов
"""

# Реэкспорт глобального exception hook
from .submodules.Msm_32_1_global_exception_hook import (
    install_global_exception_hook,
    uninstall_global_exception_hook,
    track_exception
)

__all__ = [
    'TelemetryManager',
    'track_function', 'track_exception',
    'install_global_exception_hook', 'uninstall_global_exception_hook',
]

import sys
import time
import hashlib
import platform
import traceback
import threading
import random
from typing import Optional, Dict, Any, List, Callable
from functools import wraps

from qgis.core import Qgis, QgsApplication

from Daman_QGIS.constants import (
    API_TIMEOUT, PLUGIN_VERSION, DEFAULT_MAX_RETRIES,
    TELEMETRY_LEVEL, TELEMETRY_SAMPLING_RATE, get_api_url
)
from Daman_QGIS.utils import log_info, log_error, log_warning




class TelemetryManager:
    """
    Менеджер телеметрии.

    Собирает события, батчит и отправляет на сервер.
    """

    # Интервал автоматической отправки (секунды)
    FLUSH_INTERVAL = 300  # 5 минут

    # Максимум событий в памяти перед принудительной отправкой
    MAX_EVENTS_BUFFER = 50

    # Retry параметры
    MAX_RETRIES = DEFAULT_MAX_RETRIES  # Используется из constants.py
    RETRY_DELAYS = [1, 2, 4]  # Exponential backoff: 1s, 2s, 4s

    def __init__(self):
        self._events: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._uid: Optional[str] = None
        self._hardware_id: Optional[str] = None
        self._session = None
        self._last_flush = time.time()
        self._send_thread: Optional[threading.Thread] = None

        # Базовая информация о системе (собираем один раз)
        self._system_info = self._collect_system_info()

    # Доменная соль для хэширования телеметрии (необратимое преобразование)
    _TELEMETRY_SALT = "daman-qgis-telemetry-v1"

    @staticmethod
    def _derive_telemetry_id(api_key: str) -> str:
        """
        Вычислить необратимый идентификатор для телеметрии из API ключа.

        SHA-256 с доменной солью. Результат невозможно обратить в api_key.
        Один и тот же api_key всегда даёт одинаковый telemetry_id
        (для корреляции событий одного пользователя).

        Args:
            api_key: Полный API ключ (DAMAN-XXXX-XXXX-XXXX)

        Returns:
            Строка вида "telem_<16 hex символов>"
        """
        salted = f"{TelemetryManager._TELEMETRY_SALT}:{api_key}"
        hash_hex = hashlib.sha256(salted.encode('utf-8')).hexdigest()
        return f"telem_{hash_hex[:16]}"

    def set_uid(self, api_key: str, hardware_id: str = None) -> None:
        """
        Установить UID и Hardware ID для телеметрии.

        API ключ хэшируется (SHA-256 + доменная соль) перед сохранением.
        Raw API ключ НЕ сохраняется и НЕ отправляется на сервер.

        При установке UID автоматически отправляются накопленные события.

        Args:
            api_key: Полный API ключ (DAMAN-XXXX-XXXX-XXXX)
            hardware_id: Hardware ID компьютера
        """
        if api_key:
            self._uid = self._derive_telemetry_id(api_key)
        if hardware_id:
            self._hardware_id = hardware_id

        # Auto-flush накопленных событий при установке UID
        if api_key and self._events:
            log_info(f"M_32: Flushing {len(self._events)} pending events")
            self.flush()

    def _collect_system_info(self) -> Dict[str, str]:
        """Собрать информацию о системе (один раз при инициализации)."""
        # Определяем ОС
        os_type = 'unknown'
        system = platform.system().lower()
        if system == 'windows':
            os_type = 'win'
        elif system == 'linux':
            os_type = 'linux'
        elif system == 'darwin':
            os_type = 'mac'

        # Версия Python (только major.minor)
        py_version = f"{sys.version_info.major}.{sys.version_info.minor}"

        # Версия QGIS
        try:
            qgis_version = Qgis.QGIS_VERSION
        except Exception:
            qgis_version = 'unknown'

        return {
            'v': PLUGIN_VERSION,
            'qgis': qgis_version,
            'os': os_type,
            'py': py_version
        }

    def _get_session(self):
        """Ленивая инициализация requests session."""
        if self._session is None:
            try:
                import requests
                self._session = requests.Session()
            except ImportError:
                log_warning("M_32: requests library not available")
        return self._session

    def _should_send_event(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Определить нужно ли отправлять событие на основе TELEMETRY_LEVEL.

        Args:
            event_type: Тип события
            data: Данные события (используется для проверки success/failure)

        Returns:
            True если событие нужно отправить
        """
        # Нормализуем уровень телеметрии к верхнему регистру (защита от опечаток)
        level = TELEMETRY_LEVEL.upper() if isinstance(TELEMETRY_LEVEL, str) else 'UNKNOWN'

        if level == 'ALL':
            # Отправляем всё
            return True

        if level == 'CRITICAL':
            # Только ошибки (error событие включает crashes через global exception hook)
            return event_type == 'error'

        if level == 'ERROR':
            # Ошибки + критические API failures
            if event_type == 'error':
                return True
            if event_type == 'api_call' and data:
                # Отправляем API call только если status >= 400
                status = data.get('status', 0)
                return status >= 400 or not data.get('success', True)
            return False

        if level == 'SAMPLING':
            # Минимальная статистика + все ошибки
            if event_type == 'error':
                return True

            if event_type == 'function_end':
                # Success events - sample 1%
                # Failure events - 100%
                if data and data.get('success', True):
                    # Success - применяем sampling
                    return random.random() < TELEMETRY_SAMPLING_RATE
                else:
                    # Failure - всегда отправляем
                    return True

            if event_type == 'api_call':
                # Success - не отправляем
                # Failure - всегда отправляем
                if data:
                    status = data.get('status', 0)
                    return status >= 400 or not data.get('success', True)
                return False

            # Остальные события (startup, function_start) - не отправляем
            return False

        # По умолчанию (неизвестный уровень) - не отправляем
        log_warning(f"M_32: Unknown TELEMETRY_LEVEL '{level}' (original: '{TELEMETRY_LEVEL}'), event not sent")
        return False

    def track_event(
        self,
        event_type: str,
        data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Записать событие.

        Args:
            event_type: Тип события (startup, function_start, error, etc.)
            data: Дополнительные данные события
        """
        # Проверяем нужно ли отправлять это событие
        if not self._should_send_event(event_type, data):
            return

        event = {
            'ts': int(time.time()),
            'event': event_type,
            **self._system_info
        }

        if data:
            event['data'] = self._sanitize_data(data)

        with self._lock:
            self._events.append(event)

            # Автоматический flush при переполнении буфера
            if len(self._events) >= self.MAX_EVENTS_BUFFER:
                self._do_flush()

    def track_function_start(self, func_id: str) -> None:
        """Записать начало выполнения функции."""
        self.track_event('function_start', {'func': func_id})

    def track_function_end(
        self,
        func_id: str,
        success: bool,
        duration_ms: int,
        extra: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Записать завершение функции.

        Args:
            func_id: Идентификатор функции (F_1_1, F_2_1, etc.)
            success: Успешно ли завершилась
            duration_ms: Время выполнения в миллисекундах
            extra: Дополнительные данные (layer_count, feature_count)
        """
        data = {
            'func': func_id,
            'success': success,
            'duration_ms': duration_ms
        }
        if extra:
            data.update(extra)

        self.track_event('function_end', data)

    def track_error(
        self,
        func_id: str,
        error: Exception,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Записать ошибку.

        Args:
            func_id: Где произошла ошибка
            error: Исключение
            context: Контекст ошибки
        """
        # Получаем traceback
        tb_lines = traceback.format_exception(type(error), error, error.__traceback__)

        # Санитизируем стек - убираем пути пользователя
        sanitized_stack = []
        for line in tb_lines:
            # Убираем полные пути, оставляем только имя файла и номер строки
            if 'File "' in line:
                # Извлекаем только имя файла
                parts = line.split('"')
                if len(parts) >= 2:
                    file_path = parts[1]
                    file_name = file_path.split('\\')[-1].split('/')[-1]
                    line = line.replace(file_path, file_name)
            sanitized_stack.append(line.strip())

        data = {
            'func': func_id,
            'error_type': type(error).__name__,
            'error_msg': str(error)[:500],  # Ограничиваем длину
            'stack': sanitized_stack[-10:]  # Последние 10 строк стека
        }

        if context:
            data['context'] = context

        self.track_event('error', data)

    def track_api_call(
        self,
        api_name: str,
        success: bool,
        duration_ms: int,
        status_code: Optional[int] = None
    ) -> None:
        """Записать вызов внешнего API."""
        data = {
            'api': api_name,
            'success': success,
            'duration_ms': duration_ms
        }
        if status_code:
            data['status'] = status_code

        self.track_event('api_call', data)

    def _sanitize_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Санитизация данных - удаление PII.

        Заменяет:
        - Пути файлов -> [PATH]
        - Имена проектов -> [PROJECT]
        - Длинные строки -> обрезка
        """
        sanitized = {}

        for key, value in data.items():
            if isinstance(value, str):
                # Проверяем на путь
                if '\\' in value or '/' in value:
                    # Это похоже на путь - заменяем
                    sanitized[key] = '[PATH]'
                elif len(value) > 200:
                    # Слишком длинная строка - обрезаем
                    sanitized[key] = value[:200] + '...'
                else:
                    sanitized[key] = value
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_data(value)
            elif isinstance(value, (int, float, bool)):
                sanitized[key] = value
            elif isinstance(value, list):
                # Для списков ограничиваем размер
                if len(value) > 20:
                    sanitized[key] = f'[list:{len(value)} items]'
                else:
                    sanitized[key] = value
            else:
                # Неизвестный тип - пропускаем
                sanitized[key] = str(type(value).__name__)

        return sanitized

    def flush(self) -> bool:
        """
        Отправить накопленные события на сервер (асинхронно).

        Returns:
            True если отправка запущена
        """
        with self._lock:
            return self._do_flush()

    def flush_sync(self, timeout: float = 2.0) -> bool:
        """
        Синхронная отправка с ожиданием завершения.

        Используется при shutdown для гарантии отправки событий.

        Args:
            timeout: Максимальное время ожидания в секундах (default 2.0)

        Returns:
            True если отправка завершилась в пределах timeout
        """
        result = self.flush()
        if result and self._send_thread and self._send_thread.is_alive():
            self._send_thread.join(timeout=timeout)
            return not self._send_thread.is_alive()
        return result

    def _do_flush(self) -> bool:
        """Внутренняя отправка (вызывается под lock)."""
        if not self._events:
            return True

        if not self._uid:
            log_warning("M_32: UID not set, skipping telemetry flush")
            return False

        events_to_send = self._events.copy()
        self._events.clear()
        self._last_flush = time.time()

        # Отправляем в отдельном потоке чтобы не блокировать UI
        self._send_thread = threading.Thread(
            target=self._send_events,
            args=(events_to_send,),
            daemon=True
        )
        self._send_thread.start()

        return True

    def _send_events(self, events: List[Dict[str, Any]], retry_count: int = 0) -> None:
        """Отправка событий на сервер (в отдельном потоке) с retry."""
        session = self._get_session()
        if not session:
            self._restore_events(events)
            return

        try:
            url = get_api_url("telemetry")
            payload = {
                'uid': self._uid,
                'hardware_id': self._hardware_id,
                'events': events
            }

            response = session.post(
                url,
                json=payload,
                timeout=API_TIMEOUT
            )

            if response.status_code == 200:
                data = response.json()
                saved = data.get('saved', 0)
                if saved == len(events):
                    log_info(f"M_32: Telemetry sent: {saved} events")
                elif saved == 0:
                    # Server accepted but S3 failed - retry
                    raise Exception("Server reported 0 events saved")
                else:
                    log_warning(f"M_32: Partial telemetry send: {saved}/{len(events)} events")
            elif response.status_code in (500, 502, 503, 504):
                # Server error - retry
                raise Exception(f"HTTP {response.status_code}")
            else:
                log_warning(f"M_32: Telemetry send failed: {response.status_code}")

        except Exception as e:
            if retry_count < self.MAX_RETRIES:
                # Bounds check для RETRY_DELAYS - если MAX_RETRIES увеличен, используем последний delay
                delay_index = min(retry_count, len(self.RETRY_DELAYS) - 1)
                delay = self.RETRY_DELAYS[delay_index]
                log_warning(f"M_32: Telemetry send error: {e}, retry {retry_count + 1}/{self.MAX_RETRIES} in {delay}s")
                time.sleep(delay)
                self._send_events(events, retry_count + 1)
            else:
                log_warning(f"M_32: Telemetry send failed after {self.MAX_RETRIES} retries: {e}")
                self._restore_events(events)

    def _restore_events(self, events: List[Dict[str, Any]]) -> None:
        """Restore failed events to buffer for next flush."""
        with self._lock:
            # Prepend failed events (they are older)
            self._events = events + self._events
            # Limit buffer size to prevent memory issues
            max_buffer = self.MAX_EVENTS_BUFFER * 2
            if len(self._events) > max_buffer:
                self._events = self._events[:max_buffer]
                log_warning("M_32: Event buffer truncated due to persistent failures")

    def check_auto_flush(self) -> None:
        """Проверить нужен ли автоматический flush."""
        if time.time() - self._last_flush >= self.FLUSH_INTERVAL:
            self.flush()


def track_function(func_id: str):
    """
    Декоратор для автоматического трекинга функций.

    Использование:
        @track_function("F_1_1")
        def run(self):
            ...

    Args:
        func_id: Идентификатор функции
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            from Daman_QGIS.managers._registry import registry
            telemetry = registry.get('M_32')
            telemetry.track_function_start(func_id)

            start_time = time.time()
            success = False
            extra = {}

            try:
                result = func(*args, **kwargs)
                success = True
                return result
            except Exception as e:
                telemetry.track_error(func_id, e)
                raise
            finally:
                duration_ms = int((time.time() - start_time) * 1000)
                telemetry.track_function_end(func_id, success, duration_ms, extra)

        return wrapper
    return decorator
