# -*- coding: utf-8 -*-
"""
Менеджер справочных данных шифров проектов.

Загружает шифры проектов из Base_project_codes.json через Yandex Cloud API.
Используется для валидации шифров в табелях (F_6_1).
"""

from typing import List, Dict, Optional, Set
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
from Daman_QGIS.utils import log_info, log_warning


class ProjectCodesManager(BaseReferenceLoader):
    """Менеджер для работы с базой данных шифров проектов."""

    FILE_NAME = 'Base_project_codes.json'

    # Кэш для множества шифров (быстрая проверка)
    _codes_set: Optional[Set[str]] = None

    def get_all_projects(self) -> List[Dict]:
        """
        Получить список всех проектов.

        Returns:
            Список проектов с информацией:
            - code: шифр проекта (например, "25-П-37")
            - name: название объекта
            - contract_number: номер договора
            - contract_date: дата договора
            - customer: заказчик
        """
        return self._load_json(self.FILE_NAME) or []

    def get_all_codes(self) -> List[str]:
        """
        Получить список всех шифров проектов.

        Проверяет и логирует предупреждение если шифры не в верхнем регистре
        (нарушение инварианта данных).

        Returns:
            Список шифров (только коды, без дополнительной информации)
        """
        projects = self.get_all_projects()
        codes = []
        for p in projects:
            code = p.get('code', '')
            if code:
                if code != code.upper():
                    log_warning(
                        f"Msm_4_21: Шифр '{code}' не в верхнем регистре. "
                        f"Возможна проблема валидации."
                    )
                codes.append(code)
        return codes

    def is_valid_code(self, code: str) -> bool:
        """
        Проверить, является ли шифр валидным (есть в справочнике).

        Args:
            code: Шифр для проверки

        Returns:
            True если шифр найден в справочнике
        """
        if not code:
            return False

        # Используем кэшированное множество для быстрой проверки
        if ProjectCodesManager._codes_set is None:
            ProjectCodesManager._codes_set = set(self.get_all_codes())

        return code.strip() in ProjectCodesManager._codes_set

    def get_project_info(self, code: str) -> Optional[Dict]:
        """
        Получить информацию о проекте по шифру.

        Args:
            code: Шифр проекта

        Returns:
            Словарь с информацией о проекте или None если не найден
        """
        if not code:
            return None

        return self._get_by_key(
            data_getter=self.get_all_projects,
            index_key='project_codes_by_code',
            field_name='code',
            value=code.strip()
        )

    def get_project_name(self, code: str) -> Optional[str]:
        """
        Получить название проекта по шифру.

        Args:
            code: Шифр проекта

        Returns:
            Название проекта или None если не найден
        """
        project = self.get_project_info(code)
        return project.get('name') if project else None

    def search_projects(self, query: str) -> List[Dict]:
        """
        Поиск проектов по части шифра или названия.

        Args:
            query: Строка поиска

        Returns:
            Список найденных проектов
        """
        if not query:
            return []

        query_lower = query.lower().strip()
        projects = self.get_all_projects()

        results = []
        for project in projects:
            code = project.get('code', '').lower()
            name = project.get('name', '').lower()

            if query_lower in code or query_lower in name:
                results.append(project)

        return results

    @classmethod
    def clear_codes_cache(cls):
        """Очистить кэш множества шифров."""
        cls._codes_set = None

    @classmethod
    def reload(cls, filename: Optional[str] = None):
        """
        Перезагрузить данные и очистить кэш шифров.

        Args:
            filename: Имя файла для перезагрузки
        """
        super().reload(filename)
        cls.clear_codes_cache()
