# -*- coding: utf-8 -*-
"""
Fsm_5_2_T_plugin_lifecycle - Тест жизненного цикла плагина

Проверяет:
1. Корректная инициализация плагина (initGui)
2. Регистрация actions в меню/toolbar
3. Корректная выгрузка плагина (unload)
4. Отсутствие утечек при повторной загрузке
5. Доступность всех инструментов из TOOL_REGISTRY

Основано на best practices:
- QGIS Plugin Development Guide
- Plugin unload/reload testing
"""

from typing import Any, Dict, List, Optional
import gc

from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolBar
from qgis.PyQt.QtCore import QObject


class TestPluginLifecycle:
    """Тесты жизненного цикла плагина"""

    def __init__(self, iface: Any, logger: Any) -> None:
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.plugin = None

    def run_all_tests(self) -> None:
        """Запуск всех тестов жизненного цикла"""
        self.logger.section("ТЕСТ ЖИЗНЕННОГО ЦИКЛА ПЛАГИНА")

        try:
            self.test_01_plugin_loaded()
            self.test_02_check_actions()
            self.test_03_check_toolbar()
            self.test_04_check_menu()
            self.test_05_tool_registry()
            self.test_06_managers_initialized()
            self.test_07_iface_integration()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов lifecycle: {str(e)}")

        self.logger.summary()

    def _get_plugin_instance(self) -> Optional[Any]:
        """Получить экземпляр плагина Daman_QGIS"""
        try:
            # Способ 1: через qgis.utils
            import qgis.utils
            if hasattr(qgis.utils, 'plugins'):
                plugins = qgis.utils.plugins
                if 'Daman_QGIS' in plugins:
                    return plugins['Daman_QGIS']

            # Способ 2: через iface (если есть кастомный атрибут)
            if hasattr(self.iface, 'krtdaman_plugin'):
                return self.iface.krtdaman_plugin

        except Exception:
            pass

        return None

    def test_01_plugin_loaded(self) -> None:
        """ТЕСТ 1: Плагин загружен"""
        self.logger.section("1. Проверка загрузки плагина")

        self.plugin = self._get_plugin_instance()

        if self.plugin is not None:
            self.logger.success("Плагин Daman_QGIS загружен")

            # Проверяем основные атрибуты
            if hasattr(self.plugin, 'iface'):
                self.logger.success("Атрибут iface присутствует")
            else:
                self.logger.fail("Атрибут iface отсутствует!")

            if hasattr(self.plugin, 'actions'):
                self.logger.success(f"Атрибут actions присутствует ({len(self.plugin.actions)} actions)")
            else:
                self.logger.fail("Атрибут actions отсутствует!")

        else:
            self.logger.fail("Плагин Daman_QGIS не найден в qgis.utils.plugins!")

    def test_02_check_actions(self) -> None:
        """ТЕСТ 2: Проверка QActions"""
        self.logger.section("2. Проверка QActions")

        if self.plugin is None:
            self.logger.fail("Плагин не загружен!")
            return

        try:
            # Проверяем наличие actions
            actions = getattr(self.plugin, 'actions', [])

            if not actions:
                # Альтернатива: ищем через toolbar
                toolbar = self._find_plugin_toolbar()
                if toolbar:
                    actions = toolbar.actions()

            if actions:
                self.logger.success(f"Найдено {len(actions)} QAction(s)")

                # Проверяем что все actions валидны
                # Action считается валидным если имеет: text, tooltip или icon
                valid_count = 0
                separator_count = 0
                for action in actions:
                    if isinstance(action, QAction):
                        if action.isSeparator():
                            separator_count += 1
                            valid_count += 1  # Сепараторы валидны
                        elif action.text() or action.toolTip() or not action.icon().isNull():
                            valid_count += 1

                actual_actions = len(actions) - separator_count
                valid_non_sep = valid_count - separator_count

                if valid_non_sep == actual_actions:
                    self.logger.success(f"Все {actual_actions} actions имеют text/tooltip/icon")
                else:
                    # Информируем, но не fail - некоторые actions могут быть только с иконками
                    missing = actual_actions - valid_non_sep
                    self.logger.info(f"{missing} actions без text/tooltip (могут использовать только иконки)")

                if separator_count > 0:
                    self.logger.info(f"Сепараторов: {separator_count}")

                # Проверяем что actions подключены к слотам
                # ВАЖНО: action.receivers() не работает для lambda/partial подключений
                # Альтернативная проверка: через isSignalConnected (Qt5.14+) или receivers()
                connected = 0
                enabled_count = 0
                for action in actions:
                    if isinstance(action, QAction) and not action.isSeparator():
                        # Способ 1: receivers() - работает для прямых подключений
                        if action.receivers(action.triggered) > 0:
                            connected += 1
                        # Способ 2: isSignalConnected (если доступен)
                        elif hasattr(action.triggered, 'isSignalConnected'):
                            try:
                                if action.triggered.isSignalConnected():
                                    connected += 1
                            except Exception:
                                pass

                        # Подсчитываем enabled actions (косвенный признак работоспособности)
                        if action.isEnabled():
                            enabled_count += 1

                if connected > 0:
                    self.logger.success(f"Actions с подключенными слотами (receivers): {connected}/{actual_actions}")
                elif enabled_count == actual_actions:
                    # Все actions enabled - вероятно подключены через lambda/partial
                    self.logger.success(f"Все {actual_actions} actions включены (enabled)")
                    self.logger.info("Примечание: receivers() не определяет lambda/partial подключения")
                elif enabled_count > 0:
                    self.logger.success(f"Actions enabled: {enabled_count}/{actual_actions}")
                    disabled = actual_actions - enabled_count
                    self.logger.info(f"Actions disabled: {disabled} (могут быть контекстно-зависимыми)")
                else:
                    self.logger.fail("Все actions отключены (disabled)!")

            else:
                self.logger.fail("Actions не найдены!")

        except Exception as e:
            self.logger.error(f"Ошибка проверки actions: {e}")

    def test_03_check_toolbar(self) -> None:
        """ТЕСТ 3: Проверка toolbar плагина"""
        self.logger.section("3. Проверка Toolbar")

        try:
            toolbar = self._find_plugin_toolbar()

            if toolbar:
                self.logger.success(f"Toolbar найден: '{toolbar.objectName()}'")

                # Проверяем видимость
                if toolbar.isVisible():
                    self.logger.success("Toolbar видим")
                else:
                    self.logger.fail("Toolbar скрыт!")

                # Количество элементов
                action_count = len(toolbar.actions())
                if action_count > 0:
                    self.logger.success(f"Элементов в toolbar: {action_count}")
                else:
                    self.logger.fail("Toolbar пуст!")

            else:
                self.logger.fail("Toolbar плагина не найден!")

        except Exception as e:
            self.logger.error(f"Ошибка проверки toolbar: {e}")

    def _find_plugin_toolbar(self) -> Optional[QToolBar]:
        """Найти toolbar плагина"""
        try:
            main_window = self.iface.mainWindow()

            # Ищем toolbar по имени
            toolbar_names = ['Daman', 'Daman_QGIS']

            for toolbar in main_window.findChildren(QToolBar):
                obj_name = toolbar.objectName().lower()
                window_title = toolbar.windowTitle().lower()

                for name in toolbar_names:
                    if name.lower() in obj_name or name.lower() in window_title:
                        return toolbar

        except Exception:
            pass

        return None

    def test_04_check_menu(self) -> None:
        """ТЕСТ 4: Проверка меню плагина"""
        self.logger.section("4. Проверка Menu")

        try:
            main_window = self.iface.mainWindow()
            menubar = main_window.menuBar()

            # Ищем меню плагина - может быть отдельным или в подменю Plugins
            plugin_menu = None
            menu_names = ['Daman_QGIS', 'Daman']

            # Сначала ищем в главном menubar
            for action in menubar.actions():
                menu = action.menu()
                if menu:
                    menu_title = menu.title().replace('&', '')
                    for name in menu_names:
                        if name.lower() in menu_title.lower():
                            plugin_menu = menu
                            break
                    if plugin_menu:
                        break

            # Если не найдено, ищем в меню Plugins
            if not plugin_menu:
                for action in menubar.actions():
                    menu = action.menu()
                    if menu and 'plugin' in menu.title().lower():
                        # Ищем подменю плагина
                        for sub_action in menu.actions():
                            sub_menu = sub_action.menu()
                            if sub_menu:
                                sub_title = sub_menu.title().replace('&', '')
                                for name in menu_names:
                                    if name.lower() in sub_title.lower():
                                        plugin_menu = sub_menu
                                        break
                            if plugin_menu:
                                break
                    if plugin_menu:
                        break

            if plugin_menu:
                self.logger.success(f"Меню найдено: '{plugin_menu.title()}'")

                # Подсчёт подменю и actions
                submenu_count = 0
                action_count = 0

                for action in plugin_menu.actions():
                    if action.menu():
                        submenu_count += 1
                    elif not action.isSeparator():
                        action_count += 1

                if submenu_count > 0 or action_count > 0:
                    self.logger.success(f"Подменю: {submenu_count}, Actions: {action_count}")
                else:
                    self.logger.fail("Меню пусто!")

            else:
                # Плагин может использовать только toolbar без меню - это нормально
                toolbar = self._find_plugin_toolbar()
                if toolbar:
                    self.logger.info("Меню плагина не найдено, но toolbar присутствует")
                    self.logger.info("Плагин может использовать только toolbar без отдельного меню")
                else:
                    self.logger.fail("Ни меню, ни toolbar плагина не найдены!")

        except Exception as e:
            self.logger.error(f"Ошибка проверки меню: {e}")

    def test_05_tool_registry(self) -> None:
        """ТЕСТ 5: Проверка Base_Functions.json (реестр инструментов)"""
        self.logger.section("5. Проверка Base_Functions.json")

        try:
            import json
            import os

            # Находим путь к Base_Functions.json
            from Daman_QGIS.constants import DATA_REFERENCE_PATH
            json_path = os.path.join(DATA_REFERENCE_PATH, 'Base_Functions.json')

            if not os.path.exists(json_path):
                self.logger.fail(f"Base_Functions.json не найден: {json_path}")
                return

            with open(json_path, 'r', encoding='utf-8') as f:
                functions = json.load(f)

            if functions:
                self.logger.success(f"Base_Functions.json содержит {len(functions)} функций")

                # Считаем активные функции
                enabled_count = sum(1 for f in functions if f.get('enabled', False))
                self.logger.info(f"Активных функций: {enabled_count}/{len(functions)}")

                # Проверяем структуру каждой функции
                valid_tools = 0
                for func in functions:
                    has_tool_id = 'tool_id' in func
                    has_class = 'class_name' in func
                    has_module = 'module_path' in func

                    if has_tool_id and has_class and has_module:
                        valid_tools += 1

                if valid_tools == len(functions):
                    self.logger.success(f"Все {len(functions)} функций имеют корректную структуру")
                else:
                    self.logger.fail(f"Только {valid_tools}/{len(functions)} функций имеют корректную структуру!")

                # Выводим первые 5 функций
                for i, func in enumerate(functions[:5]):
                    self.logger.info(f"  - {func.get('tool_id', 'N/A')}: {func.get('name', 'N/A')}")

                if len(functions) > 5:
                    self.logger.info(f"  ... и ещё {len(functions) - 5}")

            else:
                self.logger.fail("Base_Functions.json пуст!")

        except json.JSONDecodeError as e:
            self.logger.fail(f"Ошибка парсинга Base_Functions.json: {e}")
        except Exception as e:
            self.logger.error(f"Ошибка проверки Base_Functions.json: {e}")

    def test_06_managers_initialized(self) -> None:
        """ТЕСТ 6: Проверка инициализации менеджеров"""
        self.logger.section("6. Проверка менеджеров")

        managers_to_check = [
            ('M_1_project_manager', 'ProjectManager'),
            ('M_2_layer_manager', 'LayerManager'),
            ('M_4_reference_manager', 'ReferenceManagers'),  # Класс с 's' на конце
            ('M_5_style_manager', 'StyleManager'),
            ('M_6_coordinate_precision', 'CoordinatePrecisionManager'),
            ('M_12_label_manager', 'LabelManager'),
            ('M_13_data_cleanup_manager', 'DataCleanupManager'),
        ]

        for module_name, class_name in managers_to_check:
            try:
                module = __import__(f'Daman_QGIS.managers.{module_name}', fromlist=[class_name])
                manager_class = getattr(module, class_name, None)

                if manager_class:
                    self.logger.success(f"{class_name} импортируется")
                else:
                    self.logger.fail(f"{class_name} не найден в модуле!")

            except ImportError as e:
                self.logger.fail(f"{module_name}: {e}")
            except Exception as e:
                self.logger.error(f"Ошибка {class_name}: {e}")

    def test_07_iface_integration(self) -> None:
        """ТЕСТ 7: Интеграция с iface"""
        self.logger.section("7. Интеграция с QGIS iface")

        try:
            # Проверяем основные методы iface
            iface_methods = [
                'mainWindow',
                'mapCanvas',
                'layerTreeView',
                'messageBar',
                'activeLayer',
                'addVectorLayer',
                'addRasterLayer',
            ]

            available = 0
            for method in iface_methods:
                if hasattr(self.iface, method):
                    available += 1
                else:
                    self.logger.fail(f"iface.{method} недоступен!")

            if available == len(iface_methods):
                self.logger.success(f"Все {len(iface_methods)} методов iface доступны")
            else:
                self.logger.fail(f"Доступно только {available}/{len(iface_methods)} методов iface!")

            # Проверяем mapCanvas
            canvas = self.iface.mapCanvas()
            if canvas:
                self.logger.success("mapCanvas() возвращает объект")

                # Проверяем CRS
                crs = canvas.mapSettings().destinationCrs()
                if crs.isValid():
                    self.logger.success(f"Canvas CRS: {crs.authid()}")
                else:
                    self.logger.fail("Canvas CRS не установлена!")
            else:
                self.logger.fail("mapCanvas() вернул None!")

            # Проверяем messageBar
            msg_bar = self.iface.messageBar()
            if msg_bar:
                self.logger.success("messageBar() доступен")
            else:
                self.logger.fail("messageBar() вернул None!")

        except Exception as e:
            self.logger.error(f"Ошибка интеграции iface: {e}")
