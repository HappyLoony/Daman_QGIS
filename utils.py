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


def log_warning(message: str) -> None:
    """
    Логирование предупреждения.

    Args:
        message: Текст предупреждения
    """
    QgsMessageLog.logMessage(message, PLUGIN_NAME, Qgis.Warning)


def log_error(message: str) -> None:
    """
    Логирование ошибки.

    Args:
        message: Текст ошибки
    """
    QgsMessageLog.logMessage(message, PLUGIN_NAME, Qgis.Critical)


def log_success(message: str) -> None:
    """
    Логирование успешного выполнения операции.

    Args:
        message: Текст сообщения об успехе
    """
    QgsMessageLog.logMessage(message, PLUGIN_NAME, Qgis.Success)


def log_debug(message: str) -> None:
    """
    Логирование отладочного сообщения.

    Debug сообщения не отображаются в основном логе (NoLevel).

    Args:
        message: Текст отладочного сообщения
    """
    QgsMessageLog.logMessage(message, PLUGIN_NAME, Qgis.NoLevel)


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

    Args:
        class_name: Имя класса
        method_name: Имя метода
        exception: Исключение
    """
    log_error(f"{class_name}.{method_name}: Исключение - {str(exception)}")


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
