# -*- coding: utf-8 -*-
"""
Менеджер валидации целостности справочных данных.

Отвечает за:
- Проверку существования файлов баз данных
- Проверку уникальности ключей
- Проверку корректности ссылок между базами
- Формирование отчетов о найденных проблемах
"""

from typing import Dict, List
from Daman_QGIS.utils import log_info, log_warning

# Импорт всех необходимых менеджеров (относительные импорты внутри домена)
from .Msm_4_5_function_reference_manager import FunctionReferenceManager
from .Msm_4_6_layer_reference_manager import LayerReferenceManager
from .Msm_4_7_employee_reference_manager import EmployeeReferenceManager


class DataValidationManager:
    """
    Менеджер валидации целостности и консистентности баз данных

    Использует композицию для доступа ко всем необходимым менеджерам
    и проверяет связи между различными справочниками.
    """

    def __init__(
        self,
        function_manager: FunctionReferenceManager,
        layer_manager: LayerReferenceManager,
        employee_manager: EmployeeReferenceManager
    ):
        """
        Инициализация менеджера валидации

        Args:
            function_manager: Менеджер функций плагина
            layer_manager: Менеджер слоев
            employee_manager: Менеджер сотрудников
        """
        self.function_manager = function_manager
        self.layer_manager = layer_manager
        self.employee_manager = employee_manager

    def validate_consistency(self) -> Dict[str, List[str]]:
        """
        Проверка целостности и консистентности баз данных

        Проверяет:
        1. Уникальность full_name в Base_Functions
        2. Уникальность full_name в Base_layers
        3. Корректность ссылок creating_function в Base_layers -> Base_Functions
        4. Корректность ссылок work_layer_name в Land_Categories -> Base_layers
        5. Уникальность кодов в Land_Categories (code, code_code, rosreestr_code)
        6. Уникальность сотрудников в Base_employee (по ФИО)

        Returns:
            Словарь с найденными проблемами по категориям:
            {
                'duplicate_keys': [...],
                'invalid_references': [...]
            }
        """
        issues: Dict[str, List[str]] = {
            'duplicate_keys': [],
            'invalid_references': []
        }

        # 1. Проверка уникальности full_name в Base_Functions
        functions = self.function_manager.get_all_functions()
        function_names: set = set()
        for func in functions:
            full_name = func.get('full_name')
            if full_name:
                if full_name in function_names:
                    issues['duplicate_keys'].append(
                        f"Base_Functions: дублирующийся full_name '{full_name}'"
                    )
                function_names.add(full_name)

        # 2. Проверка уникальности full_name в Base_layers
        layers = self.layer_manager.get_base_layers()
        layer_names: set = set()
        for layer in layers:
            full_name = layer.get('full_name')
            if full_name:
                if full_name in layer_names:
                    issues['duplicate_keys'].append(
                        f"Base_layers: дублирующийся full_name '{full_name}'"
                    )
                layer_names.add(full_name)

        # 3. Проверка ссылок: creating_function в Base_layers -> Base_Functions
        for layer in layers:
            creating_func = layer.get('creating_function')
            if creating_func and creating_func not in ['Авто (при импорте L_1_1_1)', '-']:
                if not self.function_manager.get_function_by_full_name(creating_func):
                    issues['invalid_references'].append(
                        f"Base_layers '{layer.get('full_name')}': функция '{creating_func}' не найдена"
                    )

        # 4. Проверка ссылок: work_layer_name в Land_Categories -> Base_layers
        categories = self.layer_manager.get_land_categories()
        for category in categories:
            work_layer = category.get('work_layer_name')
            if work_layer:
                if not self.layer_manager.get_layer_by_full_name(work_layer):
                    issues['invalid_references'].append(
                        f"Land_Categories '{category.get('code')}': слой '{work_layer}' не найден"
                    )

        # 5. Проверка уникальности кодов в Land_Categories
        seen_codes: set = set()
        seen_code_codes: set = set()
        seen_rosreestr_codes: set = set()
        for category in categories:
            code = category.get('code')
            if code:
                if code in seen_codes:
                    issues['duplicate_keys'].append(
                        f"Land_Categories: дублирующийся code '{code}'"
                    )
                seen_codes.add(code)

            code_code = category.get('code_code')
            if code_code:
                if code_code in seen_code_codes:
                    issues['duplicate_keys'].append(
                        f"Land_Categories: дублирующийся code_code '{code_code}'"
                    )
                seen_code_codes.add(code_code)

            rosreestr_code = category.get('rosreestr_code')
            if rosreestr_code:
                if rosreestr_code in seen_rosreestr_codes:
                    issues['duplicate_keys'].append(
                        f"Land_Categories: дублирующийся rosreestr_code '{rosreestr_code}'"
                    )
                seen_rosreestr_codes.add(rosreestr_code)

        # 6. Проверка уникальности сотрудников в Base_employee (по ФИО)
        employees = self.employee_manager.get_employees()
        seen_employees: set = set()
        for employee in employees:
            last = employee.get('last_name', '') or ''
            first = employee.get('first_name', '') or ''
            middle = employee.get('middle_name', '') or ''
            full_name = f"{last}_{first}_{middle}"
            if full_name in seen_employees:
                issues['duplicate_keys'].append(
                    f"Base_employee: дублирующийся сотрудник '{last} {first} {middle}'"
                )
            seen_employees.add(full_name)

        return issues

    def print_validation_report(self) -> bool:
        """
        Печать отчёта о валидации в лог QGIS

        Вызывает validate_consistency() и форматирует результаты
        для вывода в лог QGIS через утилиты log_info/log_warning.

        Returns:
            True если проблем не найдено, False если есть проблемы
        """
        issues = self.validate_consistency()
        has_issues = any(issues.values())

        if not has_issues:
            log_info("Msm_4_14: Проверка целостности баз данных: ошибок не найдено")
            return True

        # Выводим найденные проблемы
        log_warning("Msm_4_14: Проверка целостности баз данных: найдены проблемы")

        if issues['duplicate_keys']:
            log_warning(f"Msm_4_14: Дублирующиеся ключи ({len(issues['duplicate_keys'])}):")
            for issue in issues['duplicate_keys']:
                log_warning(f"Msm_4_14:   - {issue}")

        if issues['invalid_references']:
            log_warning(f"Msm_4_14: Некорректные ссылки ({len(issues['invalid_references'])}):")
            for issue in issues['invalid_references']:
                log_warning(f"Msm_4_14:   - {issue}")

        return False
