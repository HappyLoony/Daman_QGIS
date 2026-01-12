# -*- coding: utf-8 -*-
"""
Менеджер справочных данных функций плагина

Обеспечивает:
- Получение списка функций для регистрации на панели
- Фильтрация по разделам и статусу enabled
- Генерация TOOLS_CONFIG для main_plugin.py
"""

from typing import List, Dict, Optional, Tuple
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader


class FunctionReferenceManager(BaseReferenceLoader):
    """Менеджер для работы с базой функций плагина"""

    FILE_NAME = 'Base_Functions.json'

    def get_all_functions(self) -> List[Dict]:
        """
        Получить список всех функций плагина

        Returns:
            Список функций с их описаниями и настройками регистрации
        """
        return self._load_json(self.FILE_NAME) or []

    # Алиас для обратной совместимости
    def get_base_functions(self) -> List[Dict]:
        """Алиас для get_all_functions() (обратная совместимость)"""
        return self.get_all_functions()

    def get_enabled_functions(self) -> List[Dict]:
        """
        Получить только включённые функции (enabled=True)

        Returns:
            Список функций с enabled=True
        """
        functions = self.get_all_functions()
        return [f for f in functions if f.get('enabled', False)]

    def get_tools_config(self) -> Dict[str, Tuple[str, str]]:
        """
        Генерация TOOLS_CONFIG для автоматической регистрации инструментов

        Возвращает словарь в формате:
        {
            'f_0_1': ('tools.F_0_project.F_0_1_new_project', 'F_0_1_NewProject'),
            ...
        }

        Returns:
            Dict[tool_id, (module_path, class_name)]
        """
        tools_config = {}
        functions = self.get_enabled_functions()

        for func in functions:
            tool_id = func.get('tool_id')
            module_path = func.get('module_path')
            class_name = func.get('class_name')

            # Пропускаем если нет обязательных полей
            if not all([tool_id, module_path, class_name]):
                continue

            tools_config[tool_id] = (module_path, class_name)

        return tools_config

    def get_functions_by_section(self, section_num: str) -> List[Dict]:
        """
        Получить функции по номеру раздела

        Args:
            section_num: Номер раздела (например 'F_0', 'F_1')

        Returns:
            Список функций раздела
        """
        functions = self.get_all_functions()
        return [f for f in functions if f.get('section_num') == section_num]

    def get_function_by_full_name(self, full_name: str) -> Optional[Dict]:
        """
        Получить функцию по полному рабочему названию

        Args:
            full_name: Полное имя функции (например 'F_0_1_Создание нового проекта')

        Returns:
            Словарь с информацией о функции или None
        """
        functions = self.get_all_functions()
        for func in functions:
            if func.get('full_name') == full_name:
                return func
        return None

    def get_function_by_tool_id(self, tool_id: str) -> Optional[Dict]:
        """
        Получить функцию по tool_id

        Args:
            tool_id: ID инструмента (например 'f_0_1')

        Returns:
            Словарь с информацией о функции или None
        """
        functions = self.get_all_functions()
        for func in functions:
            if func.get('tool_id') == tool_id:
                return func
        return None

    def get_function_by_num(self, section_num: str, function_num: str) -> Optional[Dict]:
        """
        Получить функцию по номеру раздела и номеру функции

        Args:
            section_num: Номер раздела (например 'F_0')
            function_num: Номер функции (например '1')

        Returns:
            Словарь с информацией о функции или None
        """
        functions = self.get_functions_by_section(section_num)
        for func in functions:
            if func.get('function_num') == function_num:
                return func
        return None

    def get_function_sections(self) -> List[Dict]:
        """
        Получить список уникальных разделов функций

        Returns:
            Список разделов [{section_num, section}, ...]
        """
        functions = self.get_all_functions()
        sections_dict = {}

        for func in functions:
            section_num = func.get('section_num')
            section = func.get('section')
            if section_num and section and section_num not in sections_dict:
                sections_dict[section_num] = {
                    'section_num': section_num,
                    'section': section
                }

        return list(sections_dict.values())

    def is_function_enabled(self, tool_id: str) -> bool:
        """
        Проверить включена ли функция

        Args:
            tool_id: ID инструмента (например 'f_0_1')

        Returns:
            True если функция включена
        """
        func = self.get_function_by_tool_id(tool_id)
        if func:
            return func.get('enabled', False)
        return False

    def get_disabled_functions(self) -> List[Dict]:
        """
        Получить список отключённых функций (для информации)

        Returns:
            Список функций с enabled=False или без module_path/class_name
        """
        functions = self.get_all_functions()
        disabled = []

        for func in functions:
            if not func.get('enabled', False):
                disabled.append(func)
            elif not func.get('module_path') or not func.get('class_name'):
                disabled.append(func)

        return disabled
