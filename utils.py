# -*- coding: utf-8 -*-
"""
Вспомогательные функции для плагина Daman_QGIS.
Упрощение часто используемых операций.
"""

import re
from pathlib import Path
from typing import List, Optional

from qgis.core import QgsMessageLog, Qgis
from Daman_QGIS.constants import PLUGIN_NAME


# ============================================================================
# ФУНКЦИИ ЛОГИРОВАНИЯ
# ============================================================================


def log_info(message: str) -> None:
    """
    Логирование информационного сообщения.

    Args:
        message: Текст сообщения
    """
    QgsMessageLog.logMessage(message, PLUGIN_NAME, Qgis.Info)
    _write_to_session_log(message, "INFO")


def log_warning(message: str) -> None:
    """
    Логирование предупреждения.

    Args:
        message: Текст предупреждения
    """
    QgsMessageLog.logMessage(message, PLUGIN_NAME, Qgis.Warning)
    _write_to_session_log(message, "WARNING")


def log_error(message: str, send_telemetry: bool = True) -> None:
    """
    Логирование ошибки.

    Автоматически отправляет ошибку в телеметрию (если включена).
    MODULE_ID извлекается из префикса сообщения (F_X_Y:, Fsm_X_Y_Z:, M_X: и т.д.)

    Args:
        message: Текст ошибки
        send_telemetry: Отправлять ли в телеметрию (по умолчанию True)
    """
    QgsMessageLog.logMessage(message, PLUGIN_NAME, Qgis.Critical)
    _write_to_session_log(message, "CRITICAL")

    # Отправка в телеметрию
    if send_telemetry:
        _send_error_to_telemetry(message)


def _send_error_to_telemetry(message: str) -> None:
    """
    Отправка ошибки в телеметрию.

    Извлекает MODULE_ID из префикса сообщения и отправляет через TelemetryManager.
    Выполняется в try/except чтобы не ломать основной код при ошибках телеметрии.

    Args:
        message: Текст ошибки
    """
    try:
        # Ленивый импорт для избежания циклических зависимостей
        from Daman_QGIS.managers import registry
        telemetry = registry.get('M_32')

        if telemetry is None:
            return

        # Извлекаем MODULE_ID из префикса сообщения
        # Форматы: "F_1_2: ...", "Fsm_3_1_7: ...", "M_26: ...", "Msm_21_1: ..."
        module_id = "unknown"
        if ': ' in message:
            prefix = message.split(': ', 1)[0]
            # Проверяем что это похоже на MODULE_ID
            if re.match(r'^(F_\d+_\d+|Fsm_\d+_\d+_\d+|M_\d+|Msm_\d+_\d+)', prefix):
                module_id = prefix

        # Извлекаем текст ошибки (после MODULE_ID)
        error_msg = message.split(': ', 1)[1] if ': ' in message else message

        # Отправляем в телеметрию (track_event, не track_error - нет Exception объекта)
        telemetry.track_event('error', {
            'func': module_id,
            'error_type': 'LogError',
            'error_msg': error_msg,
            'stack': []
        })
    except Exception:
        # Игнорируем ошибки телеметрии - не должны ломать основной код
        pass


def _write_to_session_log(message: str, level: str) -> None:
    """
    Дублирование лога в файл сессии через M_38_SessionLogManager.

    Обёрнут в try/except — не ломает основное логирование если M_38 не инициализирован.

    Args:
        message: Текст сообщения
        level: Уровень логирования (INFO, WARNING, CRITICAL, SUCCESS, DEBUG)
    """
    try:
        from Daman_QGIS.managers._registry import registry
        session_log = registry.get('M_38')
        if session_log and session_log._initialized:
            session_log.write(message, tag=PLUGIN_NAME, level=level)
    except Exception:
        pass  # Не ломаем основное логирование


def log_success(message: str) -> None:
    """
    Логирование успешного выполнения операции.

    Args:
        message: Текст сообщения об успехе
    """
    QgsMessageLog.logMessage(message, PLUGIN_NAME, Qgis.Success)
    _write_to_session_log(message, "SUCCESS")


def log_debug(message: str) -> None:
    """
    Логирование отладочного сообщения.

    Debug сообщения НЕ выводятся в QGIS Log Messages панель,
    только в session log файл (для анализа при отладке).

    Args:
        message: Текст отладочного сообщения
    """
    _write_to_session_log(message, "DEBUG")


# ============================================================================
# ФУНКЦИИ ЛОГИРОВАНИЯ С КОНТЕКСТОМ
# ============================================================================

def log_method_entry(class_name: str, method_name: str) -> None:
    """
    Логирование входа в метод (для отладки).

    Args:
        class_name: Имя класса
        method_name: Имя метода
    """
    log_debug(f"{class_name}.{method_name}: Вход")


def log_method_exit(
    class_name: str, method_name: str, success: bool = True
) -> None:
    """
    Логирование выхода из метода (для отладки).

    Args:
        class_name: Имя класса
        method_name: Имя метода
        success: Успешно ли завершился метод
    """
    status = "Успех" if success else "Ошибка"
    log_debug(f"{class_name}.{method_name}: Выход ({status})")


def log_exception(
    class_name: str, method_name: str, exception: Exception
) -> None:
    """
    Логирование исключения с контекстом.

    Автоматически отправляет в телеметрию со стеком вызовов.

    Args:
        class_name: Имя класса
        method_name: Имя метода
        exception: Исключение
    """
    import traceback

    message = f"{class_name}.{method_name}: Исключение - {str(exception)}"
    QgsMessageLog.logMessage(message, PLUGIN_NAME, Qgis.Critical)

    # Отправка в телеметрию с полным стеком
    try:
        from Daman_QGIS.managers import registry
        telemetry = registry.get('M_32')

        if telemetry is not None:
            stack = traceback.format_exc().split('\n')
            telemetry.track_error(
                func_id=f"{class_name}.{method_name}",
                error_type=type(exception).__name__,
                error_msg=str(exception),
                stack=stack
            )
    except Exception:
        pass  # Игнорируем ошибки телеметрии


# ============================================================================
# ФУНКЦИИ ЛОГИРОВАНИЯ ДЛЯ ЧАСТО ИСПОЛЬЗУЕМЫХ СЦЕНАРИЕВ
# ============================================================================

def log_layer_operation(
    operation: str, layer_name: str, success: bool = True
) -> None:
    """
    Логирование операции со слоем.

    Args:
        operation: Название операции (напр. "Загрузка слоя", "Сохранение слоя")
        layer_name: Имя слоя
        success: Успешна ли операция
    """
    if success:
        log_info(f"{operation}: Слой '{layer_name}' - успешно")
    else:
        log_error(f"{operation}: Слой '{layer_name}' - ошибка")


def log_file_operation(
    operation: str, file_path: str, success: bool = True
) -> None:
    """
    Логирование операции с файлом.

    Args:
        operation: Название операции (напр. "Чтение файла", "Запись файла")
        file_path: Путь к файлу
        success: Успешна ли операция
    """
    if success:
        log_info(f"{operation}: {file_path} - успешно")
    else:
        log_error(f"{operation}: {file_path} - ошибка")


def log_validation_error(item: str, error: str) -> None:
    """
    Логирование ошибки валидации.

    Args:
        item: Элемент, который проверялся (напр. "Геометрия", "Координаты")
        error: Текст ошибки
    """
    log_warning(f"Ошибка валидации ({item}): {error}")


def log_progress(operation: str, current: int, total: int) -> None:
    """
    Логирование прогресса операции.

    Args:
        operation: Название операции
        current: Текущий номер
        total: Всего элементов
    """
    if total > 0:
        percentage = int((current / total) * 100)
        log_info(f"{operation}: {current}/{total} ({percentage}%)")


# ============================================================================
# ФОРМАТИРОВАНИЕ
# ============================================================================


def format_file_size(size_bytes: int) -> str:
    """Форматирование размера файла в человекочитаемый вид."""
    if size_bytes < 1024:
        return f"{size_bytes} Б"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} КБ"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} МБ"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} ГБ"


# ============================================================================
# ВАЛИДАЦИЯ ПУТЕЙ (SECURITY)
# ============================================================================


class SecurityError(Exception):
    """Исключение для ошибок безопасности"""
    pass


class PathValidator:
    """Валидация путей для предотвращения path traversal"""

    @staticmethod
    def validate_user_path(base_dir: str, user_path: str, must_exist: bool = False) -> Path:
        """Валидирует путь от пользователя для предотвращения path traversal"""
        base = Path(base_dir).resolve()

        if Path(user_path).is_absolute():
            target = Path(user_path).resolve()
        else:
            target = (base / user_path).resolve()

        try:
            target.relative_to(base)
        except ValueError:
            log_error(f"Path traversal attempt detected: {user_path}")
            raise SecurityError(
                f"Path traversal attempt detected: {user_path}. "
                f"Path must be inside {base_dir}"
            )

        if must_exist and not target.exists():
            log_error(f"Path does not exist: {target}")
            raise FileNotFoundError(f"Path does not exist: {target}")

        log_debug(f"Path validated: {target}")
        return target

    @staticmethod
    def validate_file_extension(path: str, allowed_extensions: List[str]) -> bool:
        """Проверяет расширение файла"""
        ext = Path(path).suffix.lower()

        normalized_extensions = []
        for allowed_ext in allowed_extensions:
            if not allowed_ext.startswith('.'):
                allowed_ext = '.' + allowed_ext
            normalized_extensions.append(allowed_ext.lower())

        if ext not in normalized_extensions:
            log_error(f"Invalid file extension: {ext}. Allowed: {', '.join(normalized_extensions)}")
            raise ValueError(
                f"Invalid file extension: {ext}. "
                f"Allowed extensions: {', '.join(normalized_extensions)}"
            )

        log_debug(f"File extension validated: {ext}")
        return True

    @staticmethod
    def validate_project_path(project_path: str, allowed_extensions: Optional[List[str]] = None) -> Path:
        """Комплексная валидация пути к проекту"""
        if allowed_extensions is None:
            allowed_extensions = ['.qgs', '.qgz', '.gpkg']

        PathValidator.validate_file_extension(project_path, allowed_extensions)
        path = Path(project_path).resolve()
        log_debug(f"Project path validated: {path}")
        return path

# ============================================================================
# ФУНКЦИИ ОБНОВЛЕНИЯ ОТРИСОВКИ (RENDERING REFRESH)
# ============================================================================

# Уровни обновления отрисовки (по возрастанию "тяжести")
REFRESH_LIGHT = 1    # triggerRepaint для конкретного слоя
REFRESH_MEDIUM = 2   # canvas.refresh()
REFRESH_HEAVY = 3    # canvas.redrawAllLayers() - очистка кэша изображений
REFRESH_FULL = 4     # clearCache + refreshAllLayers - полная перезагрузка


def safe_refresh_layer(layer, delay_ms: int = 50) -> None:
    """
    Безопасный отложенный triggerRepaint для слоя.

    Использует QTimer.singleShot для предотвращения крашей при вызове
    refresh во время активных операций Qt.

    Args:
        layer: QgsMapLayer для обновления
        delay_ms: Задержка в миллисекундах (по умолчанию 50)

    Example:
        >>> safe_refresh_layer(my_layer)
    """
    if layer is None:
        return

    from qgis.PyQt.QtCore import QTimer

    def do_repaint():
        try:
            if layer is not None and layer.isValid():
                layer.triggerRepaint()
        except Exception:
            pass  # Игнорируем ошибки - слой мог быть удалён

    QTimer.singleShot(delay_ms, do_repaint)


def safe_refresh_canvas(level: int = REFRESH_MEDIUM, delay_ms: int = 100) -> None:
    """
    Безопасное обновление canvas с разными уровнями "тяжести".

    Уровни:
    - REFRESH_LIGHT (1): только для конкретных слоёв (используйте safe_refresh_layer)
    - REFRESH_MEDIUM (2): canvas.refresh() - базовое обновление
    - REFRESH_HEAVY (3): canvas.redrawAllLayers() - очистка кэша, перерисовка
    - REFRESH_FULL (4): clearCache + refreshAllLayers - полная перезагрузка данных

    Args:
        level: Уровень обновления (REFRESH_MEDIUM по умолчанию)
        delay_ms: Задержка в миллисекундах (по умолчанию 100)

    Example:
        >>> safe_refresh_canvas(REFRESH_HEAVY)  # После изменения стилей
        >>> safe_refresh_canvas(REFRESH_FULL)   # После серьёзных изменений
    """
    from qgis.PyQt.QtCore import QTimer
    from qgis.utils import iface

    def do_refresh():
        try:
            if iface is None or iface.mapCanvas() is None:
                return

            canvas = iface.mapCanvas()

            if level == REFRESH_MEDIUM:
                canvas.refresh()
            elif level == REFRESH_HEAVY:
                # redrawAllLayers() доступен с QGIS 3.10
                if hasattr(canvas, 'redrawAllLayers'):
                    canvas.redrawAllLayers()
                else:
                    canvas.refresh()
            elif level == REFRESH_FULL:
                # Полный сброс: очистка кэша + перезагрузка слоёв
                if hasattr(canvas, 'clearCache'):
                    canvas.clearCache()
                canvas.refreshAllLayers()
            else:
                canvas.refresh()

        except Exception as e:
            log_warning(f"safe_refresh_canvas: Ошибка при обновлении canvas: {e}")

    QTimer.singleShot(delay_ms, do_refresh)


def safe_refresh_layer_symbology(layer, delay_ms: int = 50) -> None:
    """
    Безопасное обновление символики слоя в Layer Tree.

    Обновляет отображение символики слоя в панели слоёв (легенде).
    Вызывать после изменения renderer/стиля слоя.

    Args:
        layer: QgsMapLayer для обновления
        delay_ms: Задержка в миллисекундах (по умолчанию 50)

    Example:
        >>> layer.setRenderer(new_renderer)
        >>> safe_refresh_layer_symbology(layer)
    """
    if layer is None:
        return

    from qgis.PyQt.QtCore import QTimer
    from qgis.utils import iface

    def do_refresh():
        try:
            if layer is None or not layer.isValid():
                return
            if iface is None or iface.layerTreeView() is None:
                return

            iface.layerTreeView().refreshLayerSymbology(layer.id())
        except Exception:
            pass  # Игнорируем ошибки

    QTimer.singleShot(delay_ms, do_refresh)


# ============================================================================
# ФУНКЦИИ РАБОТЫ С CRS
# ============================================================================


def create_crs_from_string(crs_value):
    """
    Безопасное создание QgsCoordinateReferenceSystem из строки или числа.

    Обрабатывает различные форматы CRS:
    - Число: 3857 -> EPSG:3857
    - Строка с числом: '3857' -> EPSG:3857
    - EPSG формат: 'EPSG:3857' -> EPSG:3857
    - Пользовательская CRS: 'USER:100021' -> USER:100021

    Args:
        crs_value: Значение CRS (int, str, или None)

    Returns:
        QgsCoordinateReferenceSystem or None: Валидная CRS или None при ошибке

    Example:
        >>> crs = create_crs_from_string('3857')
        >>> crs = create_crs_from_string('USER:100021')
        >>> crs = create_crs_from_string(3857)
    """
    from qgis.core import QgsCoordinateReferenceSystem

    if not crs_value:
        return None

    try:
        # Если это уже число
        if isinstance(crs_value, int):
            if crs_value > 0:
                crs = QgsCoordinateReferenceSystem(f"EPSG:{crs_value}")
                if crs.isValid():
                    return crs
            return None

        # Если это строка
        if isinstance(crs_value, str):
            crs_str = str(crs_value).strip()

            # Пользовательская CRS (USER:XXXXX)
            if crs_str.upper().startswith('USER:'):
                crs = QgsCoordinateReferenceSystem(crs_str)
                if crs.isValid():
                    log_info(f"Используется пользовательская CRS: {crs_str} - {crs.description()}")
                    return crs
                else:
                    log_warning(f"Невалидная пользовательская CRS: {crs_str}")
                    return None

            # EPSG формат (EPSG:XXXXX)
            if crs_str.upper().startswith('EPSG:'):
                crs = QgsCoordinateReferenceSystem(crs_str)
                if crs.isValid():
                    return crs
                else:
                    log_warning(f"Невалидный EPSG код: {crs_str}")
                    return None

            # Попытка преобразовать в число (чистый EPSG код)
            try:
                epsg_code = int(crs_str)
                if epsg_code > 0:
                    crs = QgsCoordinateReferenceSystem(f"EPSG:{epsg_code}")
                    if crs.isValid():
                        return crs
            except ValueError:
                # Не число - пробуем напрямую
                crs = QgsCoordinateReferenceSystem(crs_str)
                if crs.isValid():
                    return crs

        log_warning(f"Не удалось создать CRS из значения: {crs_value}")
        return None

    except Exception as e:
        log_error(f"Ошибка при создании CRS из '{crs_value}': {e}")
        return None
