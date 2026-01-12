# -*- coding: utf-8 -*-
"""
Главная панель инструментов с нумерованным меню
"""
from qgis.PyQt.QtWidgets import QToolButton, QMenu
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsMessageLog, Qgis
from Daman_QGIS.constants import MESSAGE_SHORT_DURATION, MESSAGE_SUCCESS_DURATION


def _build_menu_from_database() -> dict:
    """
    Построить структуру меню из Base_Functions.json

    Использует tool_id напрямую из базы данных для централизации.
    Сортирует разделы по section_num и функции по function_num,
    независимо от порядка записей в JSON.

    Returns:
        dict: Структура меню {раздел: {пункт: tool_id}}

    Example:
        База: {"section_num": "F_2", "section": "Обработка", "full_name": "3_..._Заливки", "tool_id": "F_2_3"}
        Результат: {"2_Обработка": {"3_..._Заливки": "F_2_3"}}
    """
    from Daman_QGIS.managers import get_reference_managers

    managers = get_reference_managers()
    functions = managers.function.get_base_functions()

    # Сортировка функций по section_num и function_num
    def sort_key(func):
        # Извлекаем числовую часть из section_num (F_0 -> 0, F_1 -> 1, ...)
        section_num = func.get('section_num', 'F_99')
        try:
            section_order = int(section_num.replace('F_', ''))
        except ValueError:
            section_order = 99

        # Извлекаем числовую часть из function_num
        func_num = func.get('function_num', '99')
        try:
            func_order = int(func_num)
        except ValueError:
            func_order = 99

        return (section_order, func_order)

    sorted_functions = sorted(functions, key=sort_key)

    menu = {}
    for func in sorted_functions:
        # Группировка по разделам: "F_2" → "2" + "Обработка" → "2_Обработка"
        section_num = func.get('section_num', '')
        section_name = func.get('section', '')
        section_key = section_num.replace('F_', '') + '_' + section_name

        if section_key not in menu:
            menu[section_key] = {}

        # Название пункта меню из full_name
        item_name = func.get('full_name', '')

        # tool_id напрямую из базы данных
        tool_id = func.get('tool_id', '')

        if item_name and tool_id:
            menu[section_key][item_name] = tool_id

    return menu


# Структура меню загружается динамически из Base_Functions.json
MENU_STRUCTURE = _build_menu_from_database()


class MainToolbar:
    """Главная панель с нумерованным меню"""
    
    def __init__(self, iface, toolbar):
        """
        :param iface: QGIS interface
        :param toolbar: QToolBar для добавления кнопок
        """
        self.iface = iface
        self.toolbar = toolbar
        self.tools = {}  # Зарегистрированные инструменты
        self.menu_buttons = {}  # Кнопки разделов
        
    def create_menu(self):
        """Создает нумерованное меню на панели"""
        for section_name, items in MENU_STRUCTURE.items():
            # Создаем кнопку-раздел с выпадающим меню
            tool_button = QToolButton()
            tool_button.setText(section_name)
            tool_button.setPopupMode(QToolButton.InstantPopup)
            
            # Создаем меню для раздела
            menu = QMenu()
            
            # Добавляем пункты меню
            for item_name, tool_id in items.items():
                action = menu.addAction(item_name)
                # Связываем с инструментом
                action.triggered.connect(
                    lambda checked, tid=tool_id: self.run_tool(tid)
                )
                # Состояние будет установлено через update_menu_state()
            
            tool_button.setMenu(menu)
            self.toolbar.addWidget(tool_button)
            self.menu_buttons[section_name] = tool_button
            
    def register_tool(self, tool_id, tool_instance):
        """
        Регистрирует инструмент

        :param tool_id: ID инструмента из MENU_STRUCTURE
        :param tool_instance: Экземпляр инструмента
        """
        self.tools[tool_id] = tool_instance
    def run_tool(self, tool_id):
        """
        Запускает инструмент по ID

        :param tool_id: ID инструмента
        """
        if tool_id in self.tools:
            self.tools[tool_id].run()
            self.iface.messageBar().pushMessage(
                "Success",
                f"Tool {tool_id} executed",
                level=Qgis.Success,
                duration=MESSAGE_SHORT_DURATION
            )
        else:
            self.iface.messageBar().pushMessage(
                "Not implemented",
                f"Tool {tool_id} not yet implemented",
                level=Qgis.Warning,
                duration=MESSAGE_SUCCESS_DURATION
            )
            
    def update_menu_state(self):
        """Обновляет состояние меню (активные/неактивные пункты)"""
        for section_name, tool_button in self.menu_buttons.items():
            menu = tool_button.menu()
            if menu:
                for action in menu.actions():
                    # Находим tool_id для этого action
                    item_name = action.text()
                    if section_name in MENU_STRUCTURE:
                        for name, tool_id in MENU_STRUCTURE[section_name].items():
                            if name == item_name:
                                # Активируем если инструмент зарегистрирован
                                is_registered = tool_id in self.tools
                                action.setEnabled(is_registered)
                                if not is_registered:
                                    QgsMessageLog.logMessage(
                                        f"Пункт меню '{item_name}' ({tool_id}) отключен - инструмент не зарегистрирован",
                                        "Daman_QGIS",
                                        level=Qgis.Warning
                                    )
                                break
                # Обновляем меню
                menu.update()
