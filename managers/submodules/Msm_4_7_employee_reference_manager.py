# -*- coding: utf-8 -*-
"""Менеджер справочных данных сотрудников"""

from typing import List, Dict
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader


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
            - email: отдел (ПМ/ПП)
            - position: должность
            - role_developed: включен в список "Разработал" ("ДА"/"НЕТ")
            - role_verified: включен в список "Проверил" ("ДА"/"НЕТ")
            - role_technical_director: включен в список "Техн. директор" ("ДА"/"НЕТ")
            - role_general_director: включен в список "Ген. директор" ("ДА"/"НЕТ")
        """
        return self._load_json(self.FILE_NAME) or []

    def get_employees_by_role(self, role: str) -> List[Dict]:
        """
        Получить сотрудников по роли в проекте

        Args:
            role: Роль сотрудника - 'developed', 'verified', 'technical_director', 'general_director'

        Returns:
            Список сотрудников с указанной ролью
        """
        employees = self.get_employees()
        role_map = {
            'developed': 'role_developed',
            'verified': 'role_verified',
            'technical_director': 'role_technical_director',
            'general_director': 'role_general_director'
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
