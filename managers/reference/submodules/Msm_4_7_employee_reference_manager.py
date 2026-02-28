# -*- coding: utf-8 -*-
"""Менеджер справочных данных сотрудников"""

from typing import List, Dict
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
from Daman_QGIS.utils import log_warning


class EmployeeReferenceManager(BaseReferenceLoader):
    """Менеджер для работы с базой данных сотрудников"""

    FILE_NAME = 'Base_employee.json'

    def get_employees(self) -> List[Dict]:
        """
        Получить список всех сотрудников

        Returns:
            Список сотрудников с информацией:
            - last_name: фамилия
            - first_name: имя
            - middle_name: отчество
            - company: компания
            - email: отдел (ПМ/ПП)
            - position: должность
            - rate: ставка (1.0 - полная, 0.5 - половина и т.д.)
            - role_developed: включен в список "Разработал" ("ДА"/"НЕТ")
            - role_verified: включен в список "Проверил" ("ДА"/"НЕТ")
            - role_head_of_department: включен в список "Рук. отдела" ("ДА"/"НЕТ")
            - role_normative_control: включен в список "Н. контроль" ("ДА"/"НЕТ")
        """
        return self._load_json(self.FILE_NAME) or []

    def get_employee_rate(self, employee: Dict) -> float:
        """
        Получить ставку сотрудника.

        Args:
            employee: Словарь с данными сотрудника

        Returns:
            Ставка сотрудника (по умолчанию 1.0 если не указана)
        """
        rate = employee.get('rate')
        if rate is None:
            return 1.0
        try:
            rate_value = float(rate)
            # Проверка границ: типичные ставки 0.25, 0.5, 0.75, 1.0, до 1.5
            if rate_value <= 0 or rate_value > 2.0:
                emp_name = self.get_employee_full_name(employee, format='short')
                log_warning(
                    f"Msm_4_7: Необычная ставка {rate_value} для сотрудника {emp_name}. "
                    f"Ожидается значение в диапазоне (0, 2.0]"
                )
            return rate_value
        except (ValueError, TypeError):
            return 1.0

    def get_employees_by_role(self, role: str) -> List[Dict]:
        """
        Получить сотрудников по роли в проекте

        Args:
            role: Роль сотрудника - 'developed', 'verified', 'head_of_department', 'normative_control'

        Returns:
            Список сотрудников с указанной ролью
        """
        employees = self.get_employees()
        role_map = {
            'developed': 'role_developed',
            'verified': 'role_verified',
            'head_of_department': 'role_head_of_department',
            'normative_control': 'role_normative_control'
        }

        if role not in role_map:
            return []

        field_name = role_map[role]
        # Проверяем значение "ДА" или True
        return [emp for emp in employees if emp.get(field_name) in ["ДА", True]]

    def get_employee_full_name(self, employee: Dict, format: str = 'full') -> str:
        """
        Получить полное имя сотрудника в нужном формате

        Args:
            employee: Словарь с данными сотрудника
            format: Формат имени - 'full', 'short', 'initials'
                - full: Иванов Иван Иванович
                - short: Иванов И.И.
                - initials: И.И. Иванов

        Returns:
            Отформатированное имя
        """
        last = employee.get('last_name', '') or ''
        first = employee.get('first_name', '') or ''
        middle = employee.get('middle_name', '') or ''

        if format == 'full':
            parts = [p for p in [last, first, middle] if p]
            return ' '.join(parts)
        elif format == 'short':
            first_init = first[0] + '.' if first else ''
            middle_init = middle[0] + '.' if middle else ''
            return f"{last} {first_init}{middle_init}".strip()
        elif format == 'initials':
            first_init = first[0] + '.' if first else ''
            middle_init = middle[0] + '.' if middle else ''
            return f"{first_init}{middle_init} {last}".strip()
        else:
            parts = [p for p in [last, first, middle] if p]
            return ' '.join(parts)
