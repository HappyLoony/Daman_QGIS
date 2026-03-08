# -*- coding: utf-8 -*-
"""
Msm_32_1_GlobalExceptionHook - Глобальный перехват необработанных исключений.

Устанавливает хуки для перехвата ВСЕХ необработанных исключений:
- sys.excepthook - главный поток
- threading.excepthook - дочерние потоки (Python 3.8+)

Все перехваченные исключения автоматически отправляются в телеметрию
через M_32_TelemetryManager.

Основано на best practices:
- Sentry ExcepthookIntegration
- fman.io PyQt excepthook (восстановление фреймов)
- Tim Lehr Qt message box pattern

Использование:
    from managers.submodules import install_global_exception_hook
    install_global_exception_hook()  # Вызвать один раз при старте плагина
"""

import sys
import threading
import traceback
from collections import namedtuple
from typing import Optional, Callable, Any

# Оригинальные хуки (сохраняем для восстановления и chain-вызова)
_original_excepthook: Optional[Callable] = None
_original_threading_excepthook: Optional[Callable] = None

# Флаг установки
_hooks_installed: bool = False

# Recursion guard для предотвращения бесконечной рекурсии в exception handler
_in_exception_handler: bool = False


def install_global_exception_hook() -> bool:
    """
    Установить глобальные хуки для перехвата исключений.

    Безопасно вызывать несколько раз - повторная установка игнорируется.

    Returns:
        True если хуки установлены успешно
    """
    global _hooks_installed, _original_excepthook, _original_threading_excepthook

    if _hooks_installed:
        return True

    try:
        # Сохраняем оригинальные хуки
        _original_excepthook = sys.excepthook

        # Устанавливаем наш хук для главного потока
        sys.excepthook = _global_excepthook

        # Устанавливаем хук для дочерних потоков (Python 3.8+)
        if hasattr(threading, 'excepthook'):
            _original_threading_excepthook = threading.excepthook
            threading.excepthook = _thread_excepthook

        _hooks_installed = True

        return True

    except Exception as e:
        # Если что-то пошло не так, пытаемся залогировать
        try:
            from Daman_QGIS.utils import log_error
            log_error(f"Msm_32_1: Failed to install exception hooks: {e}")
        except ImportError:
            print(f"Msm_32_1: Failed to install exception hooks: {e}")
        return False


def uninstall_global_exception_hook() -> None:
    """
    Восстановить оригинальные хуки.

    Вызывается при выгрузке плагина для корректной очистки.
    """
    global _hooks_installed, _original_excepthook, _original_threading_excepthook

    if not _hooks_installed:
        return

    try:
        # Восстанавливаем оригинальный sys.excepthook
        if _original_excepthook is not None:
            sys.excepthook = _original_excepthook

        # Восстанавливаем threading.excepthook
        if _original_threading_excepthook is not None and hasattr(threading, 'excepthook'):
            threading.excepthook = _original_threading_excepthook

        _hooks_installed = False

        try:
            from Daman_QGIS.utils import log_info
            log_info("Msm_32_1: Global exception hooks uninstalled")
        except ImportError:
            pass

    except Exception:
        pass


def _global_excepthook(exc_type, exc_value, exc_tb):
    """
    Глобальный обработчик необработанных исключений (главный поток).

    Args:
        exc_type: Тип исключения
        exc_value: Значение исключения
        exc_tb: Traceback объект
    """
    # Пропускаем KeyboardInterrupt - это нормальное завершение
    if issubclass(exc_type, KeyboardInterrupt):
        if _original_excepthook:
            _original_excepthook(exc_type, exc_value, exc_tb)
        return

    # Пропускаем SystemExit - это тоже нормальное завершение
    if issubclass(exc_type, SystemExit):
        if _original_excepthook:
            _original_excepthook(exc_type, exc_value, exc_tb)
        return

    # Отправляем в телеметрию
    _send_to_telemetry(
        source="MAIN_THREAD",
        exc_type=exc_type,
        exc_value=exc_value,
        exc_tb=exc_tb
    )

    # Вызываем оригинальный хук (для вывода в консоль и т.д.)
    if _original_excepthook:
        _original_excepthook(exc_type, exc_value, exc_tb)


def _thread_excepthook(args):
    """
    Обработчик необработанных исключений в дочерних потоках (Python 3.8+).

    Args:
        args: ExceptHookArgs с полями exc_type, exc_value, exc_traceback, thread
    """
    exc_type = args.exc_type
    exc_value = args.exc_value
    exc_tb = args.exc_traceback
    thread = args.thread

    # Пропускаем KeyboardInterrupt и SystemExit
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        if _original_threading_excepthook:
            _original_threading_excepthook(args)
        return

    # Определяем имя потока
    thread_name = thread.name if thread else "Unknown"

    # Отправляем в телеметрию
    _send_to_telemetry(
        source=f"THREAD:{thread_name}",
        exc_type=exc_type,
        exc_value=exc_value,
        exc_tb=exc_tb
    )

    # Вызываем оригинальный хук
    if _original_threading_excepthook:
        _original_threading_excepthook(args)


def _send_to_telemetry(
    source: str,
    exc_type,
    exc_value,
    exc_tb
) -> None:
    """
    Отправить исключение в телеметрию.

    Args:
        source: Источник исключения (MAIN_THREAD, THREAD:name, QGSTASK:name)
        exc_type: Тип исключения
        exc_value: Значение исключения
        exc_tb: Traceback объект
    """
    global _in_exception_handler

    # Recursion guard - предотвращаем бесконечную рекурсию
    if _in_exception_handler:
        return

    _in_exception_handler = True
    try:
        from Daman_QGIS.managers._registry import registry

        telemetry = registry.get('M_32')

        # Форматируем traceback
        # Используем технику fman.io для восстановления недостающих фреймов PyQt
        enriched_tb = _add_missing_frames(exc_tb) if exc_tb else exc_tb

        tb_lines = traceback.format_exception(exc_type, exc_value, enriched_tb)

        # Санитизируем стек - убираем пути пользователя
        sanitized_stack = _sanitize_traceback(tb_lines)

        # Пытаемся определить функцию плагина из стека
        func_id = _extract_function_id(tb_lines)

        # Формируем данные для телеметрии
        data = {
            'func': func_id or source,
            'error_type': exc_type.__name__,
            'error_msg': str(exc_value)[:500],
            'stack': sanitized_stack[-15:],  # Последние 15 строк
            'source': source
        }

        # Отправляем как событие error
        telemetry.track_event('error', data)

        # Сразу делаем СИНХРОННЫЙ flush для критических ошибок
        # (чтобы не потерять данные если приложение упадёт)
        # Ждём до 2 секунд - для crash это приемлемо
        telemetry.flush_sync(timeout=2.0)

    except Exception as e:
        # Если телеметрия недоступна - просто логируем локально
        try:
            from Daman_QGIS.utils import log_error
            log_error(f"Msm_32_1: Failed to send exception to telemetry: {e}")
        except ImportError:
            pass
    finally:
        _in_exception_handler = False


def _add_missing_frames(tb):
    """
    Восстановить недостающие фреймы в traceback для PyQt.

    PyQt иногда теряет часть стека при вызовах из сигналов/слотов.
    Техника из fman.io/blog/pyqt-excepthook/

    Args:
        tb: Оригинальный traceback объект

    Returns:
        Обогащённый traceback с восстановленными фреймами
    """
    if tb is None:
        return None

    try:
        # Создаём fake_tb namedtuple для совместимости с traceback модулем
        fake_tb = namedtuple('fake_tb', ('tb_frame', 'tb_lasti', 'tb_lineno', 'tb_next'))

        # Начинаем с текущего фрейма
        result = fake_tb(tb.tb_frame, tb.tb_lasti, tb.tb_lineno, tb.tb_next)

        # Добавляем недостающие фреймы из f_back
        frame = tb.tb_frame.f_back
        while frame:
            result = fake_tb(frame, frame.f_lasti, frame.f_lineno, result)
            frame = frame.f_back

        return result

    except Exception:
        # Если что-то пошло не так - возвращаем оригинальный tb
        return tb


def _sanitize_traceback(tb_lines: list) -> list:
    """
    Санитизировать traceback - убрать пути пользователя.

    Args:
        tb_lines: Список строк traceback

    Returns:
        Санитизированный список строк
    """
    sanitized = []

    for line in tb_lines:
        # Убираем полные пути, оставляем только имя файла
        if 'File "' in line:
            parts = line.split('"')
            if len(parts) >= 2:
                file_path = parts[1]
                # Извлекаем только имя файла
                file_name = file_path.replace('\\', '/').split('/')[-1]
                line = line.replace(file_path, file_name)

        sanitized.append(line.strip())

    return sanitized


def _extract_function_id(tb_lines: list) -> Optional[str]:
    """
    Попытаться извлечь идентификатор функции плагина из traceback.

    Ищет паттерны F_X_Y, Fsm_X_Y_Z, M_X в именах файлов и функций.

    Args:
        tb_lines: Список строк traceback

    Returns:
        Идентификатор функции или None
    """
    import re

    # Паттерны для поиска идентификаторов
    patterns = [
        r'F_\d+_\d+',           # F_1_2, F_0_1
        r'Fsm_\d+_\d+_\d+',     # Fsm_1_2_1
        r'M_\d+',              # M_1, M_32
        r'Msm_\d+_\d+',        # Msm_32_1
    ]

    # Ищем в обратном порядке (ближе к месту ошибки = важнее)
    for line in reversed(tb_lines):
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                return match.group(0)

    return None


# Функция для ручного трекинга исключений (для использования в try/except)
def track_exception(
    func_id: str,
    exc_value: Exception,
    context: Optional[dict] = None
) -> None:
    """
    Вручную отправить исключение в телеметрию.

    Используйте в блоках try/except когда хотите перехватить
    исключение, но всё равно отправить его в телеметрию.

    Args:
        func_id: Идентификатор функции (F_1_2, M_32, etc.)
        exc_value: Объект исключения
        context: Дополнительный контекст (опционально)

    Example:
        try:
            risky_operation()
        except Exception as e:
            track_exception("F_1_2", e, {"layer": layer_name})
            # Продолжаем выполнение или показываем ошибку пользователю
    """
    try:
        from Daman_QGIS.managers._registry import registry

        telemetry = registry.get('M_32')
        telemetry.track_error(func_id, exc_value, context)

    except Exception:
        # Молча игнорируем ошибки телеметрии
        pass
