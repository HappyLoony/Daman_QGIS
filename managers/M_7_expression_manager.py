# -*- coding: utf-8 -*-
"""
Менеджер QGIS выражений.
Централизованное управление выражениями для фильтров, подписей, стилей.
"""

import json
import os
from typing import Optional, Dict
from qgis.core import (
    QgsVectorLayer,
    QgsExpressionContextUtils,
    QgsProject,
    QgsExpression
)
from Daman_QGIS.utils import log_info, log_warning, log_error, log_debug
from typing import List, Tuple


class ExpressionManager:
    """Централизованный менеджер QGIS выражений

    Загружает выражения из Base_expressions.json и предоставляет методы для:
    - Получения выражений по ID
    - Применения фильтров к слоям
    - Регистрации выражений как переменных проекта

    Структура Base_expressions.json:
    {
        "expression_id": "QGIS expression string",
        ...
    }

    Naming convention для expression_id:
    - coord_*  : координаты для позиционирования подписей
    - calc_*   : вычисления (азимут, смещение, проверки)
    - filter_* : фильтры слоев (setSubsetString)
    - label_*  : выражения для подписей (fieldName с isExpression=True)
    - style_*  : выражения для стилей и категоризации

    Example:
        >>> expr_mgr = ExpressionManager()
        >>> # Получить выражение для координат
        >>> expr = expr_mgr.get('coord_top_left_x')
        >>> # Получить вычисляемое выражение
        >>> expr = expr_mgr.get('calc_bisector_azimuth')
        >>> # Зарегистрировать все как переменные проекта
        >>> expr_mgr.register_as_variables()
    """

    def __init__(self):
        """Инициализация менеджера выражений"""
        # Путь к файлу с выражениями
        from Daman_QGIS.constants import DATA_REFERENCE_PATH
        self.expressions_file = os.path.join(DATA_REFERENCE_PATH, 'Base_expressions.json')

        # Загружаем выражения
        self.expressions: Dict[str, str] = self._load()

        log_debug(f"ExpressionManager: Загружено {len(self.expressions)} выражений из {os.path.basename(self.expressions_file)}")

    def _load(self) -> Dict[str, str]:
        """Загрузка выражений из JSON файла

        Returns:
            Словарь {expression_id: expression_string}
        """
        if not os.path.exists(self.expressions_file):
            log_warning(f"ExpressionManager: Файл {self.expressions_file} не найден, создаём пустой словарь")
            return {}

        try:
            with open(self.expressions_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Проверяем что это словарь
            if not isinstance(data, dict):
                log_error(f"ExpressionManager: Base_expressions.json должен содержать словарь, получен {type(data)}")
                return {}

            # Валидация синтаксиса выражений
            valid_expressions = {}
            invalid_count = 0
            for expr_id, expr_str in data.items():
                if not isinstance(expr_str, str):
                    log_error(f"ExpressionManager: Выражение '{expr_id}' должно быть строкой, получен {type(expr_str)}")
                    invalid_count += 1
                    continue

                qgs_expr = QgsExpression(expr_str)
                if qgs_expr.hasParserError():
                    log_error(f"ExpressionManager: Синтаксическая ошибка в '{expr_id}': {qgs_expr.parserErrorString()}")
                    invalid_count += 1
                else:
                    valid_expressions[expr_id] = expr_str

            if invalid_count > 0:
                log_warning(f"ExpressionManager: {invalid_count} выражений с ошибками пропущено")

            return valid_expressions

        except json.JSONDecodeError as e:
            log_error(f"ExpressionManager: Ошибка парсинга JSON: {str(e)}")
            return {}
        except Exception as e:
            log_error(f"ExpressionManager: Ошибка загрузки выражений: {str(e)}")
            return {}

    def reload(self) -> bool:
        """Перезагрузить выражения из файла

        Returns:
            True если успешно перезагружено
        """
        self.expressions = self._load()
        log_info(f"ExpressionManager: Перезагружено {len(self.expressions)} выражений")
        return len(self.expressions) > 0

    def get(self, expr_id: str) -> Optional[str]:
        """Получить выражение по ID

        Args:
            expr_id: Идентификатор выражения (например, 'coord_top_left_x')

        Returns:
            Строка с выражением или None если не найдено

        Example:
            >>> expr = expr_mgr.get('calc_bisector_azimuth')
            >>> print(expr)  # with_variable('poly', geometry(...), ...)
        """
        expression = self.expressions.get(expr_id)

        if expression is None:
            log_warning(f"ExpressionManager: Выражение '{expr_id}' не найдено в Base_expressions.json")

        return expression

    def apply_filter(self, layer: QgsVectorLayer, expr_id: str) -> bool:
        """Применить фильтр к слою через setSubsetString

        Args:
            layer: Векторный слой
            expr_id: ID выражения фильтра (обычно начинается с 'filter_')

        Returns:
            True если фильтр успешно применён

        Example:
            >>> layer = project.mapLayersByName('L_1_2_1_WFS_ЗУ')[0]
            >>> expr_mgr.apply_filter(layer, 'filter_some_condition')
        """
        expression = self.get(expr_id)

        if not expression:
            log_error(f"ExpressionManager: Не могу применить фильтр - выражение '{expr_id}' не найдено")
            return False

        if not layer or not layer.isValid():
            log_error(f"ExpressionManager: Не могу применить фильтр - слой невалидный")
            return False

        try:
            layer.setSubsetString(expression)
            log_info(f"ExpressionManager: Фильтр '{expr_id}' применён к слою {layer.name()}")
            return True

        except Exception as e:
            log_error(f"ExpressionManager: Ошибка применения фильтра '{expr_id}': {str(e)}")
            return False

    def register_as_variables(self, project: Optional[QgsProject] = None) -> int:
        """Зарегистрировать все выражения как переменные проекта

        После регистрации выражения доступны в Expression Builder как:
        - @<expression_id> (например, @calc_bisector_azimuth)
        - var('<expression_id>')

        Это позволяет использовать eval() для вложенных выражений:
        - eval(@calc_bisector_azimuth) - вычисляет выражение из переменной

        Args:
            project: Проект QGIS (если None, используется текущий)

        Returns:
            Количество зарегистрированных переменных

        Example:
            >>> expr_mgr.register_as_variables()
            >>> # Теперь в Expression Builder можно использовать:
            >>> # @coord_top_left_x
            >>> # eval(@calc_bisector_azimuth)
        """
        if project is None:
            project = QgsProject.instance()

        if not project:
            log_error("ExpressionManager: Проект не найден")
            return 0

        count = 0
        for expr_id, expression in self.expressions.items():
            # Регистрируем без префикса - ID уже содержит тип (calc_, coord_, filter_, label_)
            # Это позволяет использовать eval(@calc_bisector_azimuth) напрямую
            try:
                QgsExpressionContextUtils.setProjectVariable(project, expr_id, expression)
                count += 1
            except Exception as e:
                log_warning(f"ExpressionManager: Не удалось зарегистрировать переменную '{expr_id}': {str(e)}")

        log_info(f"ExpressionManager: Зарегистрировано {count} переменных проекта")
        return count

    def get_all_ids(self) -> list:
        """Получить список всех ID выражений

        Returns:
            Список expression_id
        """
        return list(self.expressions.keys())

    def get_by_prefix(self, prefix: str) -> Dict[str, str]:
        """Получить все выражения с определённым префиксом

        Args:
            prefix: Префикс для фильтрации (например, 'label_', 'filter_')

        Returns:
            Словарь {expression_id: expression_string}

        Example:
            >>> label_expressions = expr_mgr.get_by_prefix('label_')
            >>> filter_expressions = expr_mgr.get_by_prefix('filter_')
        """
        return {
            expr_id: expression
            for expr_id, expression in self.expressions.items()
            if expr_id.startswith(prefix)
        }

    def validate_all(self, include_raw: bool = False) -> Tuple[List[str], List[Tuple[str, str]]]:
        """Валидация всех выражений из JSON файла (включая невалидные)

        Читает файл заново и проверяет ВСЕ выражения, включая те,
        которые были отфильтрованы при загрузке.

        Args:
            include_raw: Если True, читает файл заново для полной проверки

        Returns:
            Кортеж (valid_ids, invalid_list):
            - valid_ids: список ID валидных выражений
            - invalid_list: список кортежей (expr_id, error_message)

        Example:
            >>> valid, invalid = expr_mgr.validate_all(include_raw=True)
            >>> print(f"Валидных: {len(valid)}, с ошибками: {len(invalid)}")
            >>> for expr_id, error in invalid:
            ...     print(f"  {expr_id}: {error}")
        """
        valid_ids = []
        invalid_list = []

        # Определяем источник данных
        if include_raw:
            # Читаем файл заново для полной проверки
            try:
                with open(self.expressions_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    return [], [("_file_", f"Файл должен содержать словарь, получен {type(data)}")]
            except Exception as e:
                return [], [("_file_", f"Ошибка чтения файла: {str(e)}")]
        else:
            # Используем уже загруженные выражения
            data = self.expressions

        # Валидируем каждое выражение
        for expr_id, expr_str in data.items():
            if not isinstance(expr_str, str):
                invalid_list.append((expr_id, f"Должно быть строкой, получен {type(expr_str)}"))
                continue

            qgs_expr = QgsExpression(expr_str)
            if qgs_expr.hasParserError():
                invalid_list.append((expr_id, qgs_expr.parserErrorString()))
            else:
                valid_ids.append(expr_id)

        return valid_ids, invalid_list

    def get_validation_report(self) -> str:
        """Получить текстовый отчёт о валидации всех выражений

        Returns:
            Многострочный отчёт о состоянии выражений

        Example:
            >>> print(expr_mgr.get_validation_report())
        """
        valid, invalid = self.validate_all(include_raw=True)

        lines = [
            f"Отчёт валидации выражений ({self.expressions_file})",
            "-" * 60,
            f"Валидных выражений: {len(valid)}",
            f"С ошибками: {len(invalid)}",
        ]

        if invalid:
            lines.append("")
            lines.append("Выражения с ошибками:")
            for expr_id, error in invalid:
                lines.append(f"  - {expr_id}: {error}")

        if valid:
            lines.append("")
            lines.append("Валидные выражения:")
            for expr_id in sorted(valid):
                lines.append(f"  + {expr_id}")

        return "\n".join(lines)
