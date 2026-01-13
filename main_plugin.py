# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Daman_QGIS
                                 A QGIS plugin
 Комплексный инструмент для работы с данными в QGIS
                              -------------------
        begin                : 2025-01-29
        git sha              : $Format:%H$
        copyright            : (C) 2025 by Author
        email                : email@example.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from typing import Dict, Tuple, Optional, Callable, Any, List
from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QToolBar, QMenu, QMessageBox, QWidget
from qgis.core import QgsProject, Qgis, QgsMessageLog
from qgis.gui import QgisInterface

# Initialize Qt resources from file resources.py
# from .resources import *

import os.path
import configparser

# ВАЖНО: Инициализируем путь к dependencies ДО импорта внешних зависимостей
# Это позволяет импортировать пакеты из изолированной папки %APPDATA%/QGIS/.../python/dependencies/
from Daman_QGIS.tools.F_5_plagin.submodules.Fsm_5_1_4_pip_installer import PipInstaller
PipInstaller.ensure_dependencies_in_path()

# Import managers
from Daman_QGIS.managers import ProjectManager, LayerManager, VersionManager, get_reference_managers
from Daman_QGIS.managers.M_31_update_manager import get_update_manager

# Import dependency checker
from Daman_QGIS.tools.F_5_plagin.F_5_1_check_dependencies import F_5_1_CheckDependencies

# Import main toolbar
from Daman_QGIS.ui.main_toolbar import MainToolbar

# Import common tools
from Daman_QGIS.managers import CadnumSearchManager

# Import exception handling

# Import constants
from Daman_QGIS.constants import (
    PLUGIN_NAME, MESSAGE_SHORT_DURATION, MESSAGE_SUCCESS_DURATION,
    PLUGIN_VERSION
)

# Import logging utilities
from Daman_QGIS.utils import log_info, log_warning, log_error


def _load_tools_config() -> Dict[str, Tuple[str, str]]:
    """
    Загрузка конфигурации инструментов из Base_Functions.json

    Единственный источник истины для регистрации функций на панели.
    Если функция не найдена в JSON или enabled=False - она не регистрируется.

    Returns:
        Dict[tool_id, (module_path, class_name)]
    """
    import json
    import os
    from Daman_QGIS.constants import DATA_REFERENCE_PATH

    json_path = os.path.join(DATA_REFERENCE_PATH, 'Base_Functions.json')

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            functions = json.load(f)
    except FileNotFoundError:
        log_warning(f"Base_Functions.json не найден: {json_path}")
        return {}
    except json.JSONDecodeError as e:
        log_error(f"Ошибка парсинга Base_Functions.json: {e}")
        return {}

    tools_config = {}
    disabled_count = 0

    for func in functions:
        # Пропускаем отключенные функции
        if not func.get('enabled', False):
            disabled_count += 1
            continue

        tool_id = func.get('tool_id')
        module_path = func.get('module_path')
        class_name = func.get('class_name')

        # Пропускаем если нет обязательных полей
        if not all([tool_id, module_path, class_name]):
            continue

        tools_config[tool_id] = (module_path, class_name)

    log_info(f"TOOLS_CONFIG: загружено {len(tools_config)} функций из Base_Functions.json "
             f"(отключено: {disabled_count})")
    return tools_config


# Конфигурация инструментов - загружается из Base_Functions.json
TOOLS_CONFIG = _load_tools_config()

class DamanQGIS:
    """QGIS Plugin Implementation."""

    def __init__(self, iface: QgisInterface) -> None:
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface: QgisInterface = iface

        # Initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)

        # Initialize locale
        self.translator = QTranslator()
        locale_value = QSettings().value('locale/userLocale')
        locale = locale_value[0:2] if locale_value else 'en'
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'Daman_QGIS_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&Daman_QGIS')

        # Check if plugin is in toolbar
        self.toolbar = None
        self.main_toolbar = None  # Главное нумерованное меню
        
        # Plugin version - читаем из metadata.txt
        self.version = self._get_plugin_version()
        
        # Инициализация менеджеров
        self.project_manager = None
        self.layer_manager = None
        self.version_manager = None
        self.reference_managers = None

        # Общие инструменты (контекстное меню)
        self.cadnum_search = None

        # Реестр подключенных Qt сигналов для корректного отключения
        self._signal_connections = []

    def _get_plugin_version(self) -> str:
        """Получение версии плагина из metadata.txt"""
        try:
            metadata_path = os.path.join(self.plugin_dir, 'metadata.txt')
            config = configparser.ConfigParser()
            config.read(metadata_path)
            return config.get('general', 'version', fallback=PLUGIN_VERSION)
        except Exception as e:
            log_warning(f"Не удалось прочитать версию из metadata.txt: {str(e)}")
            return PLUGIN_VERSION  # Версия по умолчанию если не удалось прочитать
    
    # noinspection PyMethodMayBeStatic
    def tr(self, message: str) -> str:
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate(PLUGIN_NAME, message)

    def add_action(
        self,
        icon_path: str,
        text: str,
        callback: Callable[[], None],
        enabled_flag: bool = True,
        add_to_menu: bool = True,
        add_to_toolbar: bool = True,
        status_tip: Optional[str] = None,
        whats_this: Optional[str] = None,
        parent: Optional[QWidget] = None) -> QAction:
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)

        # Регистрируем подключение сигнала для последующего отключения
        self._register_signal(action.triggered, callback)

        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            # Adds plugin icon to Plugins toolbar
            self.iface.addToolBarIcon(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action
    def initGui(self) -> None:
        """Создание элементов меню и панели инструментов."""

        # Быстрая проверка зависимостей при запуске (краткий лог)
        log_info("Daman_QGIS: Запуск плагина, проверка зависимостей...")
        try:
            F_5_1_CheckDependencies.quick_check()
        except Exception as e:
            log_warning(f"Не удалось проверить зависимости: {str(e)}")
        
        # Инициализация менеджеров
        self._init_managers()

        # Инициализация общих инструментов (контекстное меню)
        self._init_common_tools()

        # Создание панели инструментов
        self.toolbar = self.iface.addToolBar(PLUGIN_NAME)
        self.toolbar.setObjectName(PLUGIN_NAME)
        
        # Создание главного нумерованного меню
        self.main_toolbar = MainToolbar(self.iface, self.toolbar)
        
        # Сначала регистрируем инструменты
        self._register_tools()
        
        # Теперь создаем меню когда инструменты уже зарегистрированы
        self.main_toolbar.create_menu()
        
        # Проверяем, не открыт ли уже проект плагина нативным способом
        self._check_native_project()
        
        # Обновляем состояние меню после его создания
        self.main_toolbar.update_menu_state()
        
        # Подключаем обработчики событий закрытия проекта
        self._connect_project_signals()

        # Проверка обновлений (отложенная, не блокирует запуск)
        self._check_for_updates()

    def _check_for_updates(self) -> None:
        """Проверка обновлений плагина при запуске."""
        try:
            update_manager = get_update_manager()
            update_manager.set_iface(self.iface)
            update_manager.check_on_startup(delay_ms=5000)
        except Exception as e:
            log_warning(f"Не удалось запустить проверку обновлений: {e}")

    def _check_native_project(self) -> None:
        """Проверка и инициализация нативно открытого проекта плагина"""
        if self.project_manager:
            # Пытаемся инициализировать из нативно открытого проекта
            if self.project_manager.init_from_native_project():
                log_info("Обнаружен и инициализирован нативно открытый проект плагина")
                self._show_project_activated_notification()
    def _init_managers(self) -> None:
        """Инициализация менеджеров плагина"""
        # Менеджер проектов
        self.project_manager = ProjectManager(self.iface, self.plugin_dir)
        self.project_manager.plugin_version = self.version

        # Менеджер слоев
        self.layer_manager = LayerManager(self.iface, self.plugin_dir)

        # Менеджер версий
        self.version_manager = VersionManager(self.iface)

        # Менеджер справочных данных
        self.reference_managers = get_reference_managers()

    def _init_common_tools(self) -> None:
        """Инициализация общих инструментов (контекстное меню)"""
        try:
            # Инициализация поиска по кадастровому номеру
            self.cadnum_search = CadnumSearchManager(self.iface)
            self.cadnum_search.init_gui()  # Важно! Инициализация GUI и контекстного меню
            log_info("Поиск по кадастровому номеру инициализирован")
        except Exception as e:
            log_warning(f"Не удалось инициализировать поиск по кадастровому номеру: {str(e)}")

    def register_tool(self, F_id: str, F_class: type) -> None:
        """Регистрация инструмента в нумерованном меню

        :param F_id: ID инструмента из MENU_STRUCTURE
        :param F_class: Класс инструмента
        """
        # Создаем экземпляр инструмента
        tool = F_class(self.iface)

        # Устанавливаем ссылки на менеджеры через цикл
        managers = {
            'plugin_dir': self.plugin_dir,
            'project_manager': self.project_manager,
            'layer_manager': self.layer_manager,
            'version_manager': self.version_manager,
            'reference_manager': self.reference_managers,
            'plugin_version': self.version
        }

        for attr_name, manager in managers.items():
            setter_name = f'set_{attr_name}'
            if hasattr(tool, setter_name):
                getattr(tool, setter_name)(manager)

        # Регистрируем в нумерованном меню
        if self.main_toolbar:
            self.main_toolbar.register_tool(F_id, tool)
    def _register_tools(self) -> None:
        """Регистрация всех доступных инструментов"""
        registered_count = 0
        failed_tools = []

        # Автоматическая регистрация инструментов из конфигурации
        for tool_id, (module_path, class_name) in TOOLS_CONFIG.items():
            try:
                # Динамический импорт модуля
                module = __import__(f'Daman_QGIS.{module_path}', fromlist=[class_name])
                tool_class = getattr(module, class_name)

                # Регистрация инструмента
                self.register_tool(tool_id, tool_class)
                registered_count += 1
            except Exception as e:
                tool_name = tool_id.upper().replace('_', ' ')
                failed_tools.append(f"{tool_name}: {str(e)}")
                log_warning(f"Не удалось загрузить {tool_name}: {str(e)}")

        # Инструменты F_3_X (Нарезка) и F_4_X (ХЛУ) будут добавлены позже

        if failed_tools:
            log_warning(f"Не удалось загрузить: {', '.join(failed_tools)}")
    
    def _register_signal(self, signal: Any, slot: Callable[..., Any]) -> None:
        """
        Регистрация подключения сигнала для последующего отключения

        Args:
            signal: Qt сигнал
            slot: Обработчик (слот)
        """
        signal.connect(slot)
        self._signal_connections.append((signal, slot))
    def _connect_project_signals(self) -> None:
        """Подключение обработчиков событий проекта с регистрацией"""
        # Сигнал очистки проекта (вызывается при закрытии)
        self._register_signal(QgsProject.instance().cleared, self._on_project_cleared)

        # Сигнал создания нового проекта (переход на другой проект)
        self._register_signal(self.iface.newProjectCreated, self._on_new_project)

        # Сигнал открытия проекта (вызывается после загрузки проекта)
        self._register_signal(QgsProject.instance().readProject, self._on_project_read)

        # Сигнал закрытия QGIS
        self._register_signal(QCoreApplication.instance().aboutToQuit, self._on_qgis_closing)
    
    def _disconnect_project_signals(self) -> None:
        """Отключение всех зарегистрированных обработчиков событий"""
        # Отключаем все зарегистрированные сигналы
        for signal, slot in self._signal_connections:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                # Игнорируем ошибки отключения (сигнал мог быть уже отключен)
                pass

        # Очищаем реестр
        self._signal_connections.clear()
    
    def _check_save_before_close(self):
        """Проверка необходимости сохранения перед закрытием"""
        # Проверяем есть ли несохраненные изменения
        if QgsProject.instance().isDirty():
            # Получаем имя проекта для отображения
            project_name = "Проект"
            if self.project_manager and self.project_manager.settings:
                project_name = self.project_manager.settings.name
            
            # Показываем диалог с двумя кнопками
            reply = QMessageBox.question(
                self.iface.mainWindow(),
                "Сохранить изменения?",
                f"В проекте '{project_name}' есть несохраненные изменения.\n"
                "Сохранить изменения перед закрытием?",
                QMessageBox.Save | QMessageBox.Discard,
                QMessageBox.Save
            )
            
            if reply == QMessageBox.Save:
                # Сохраняем проект
                if self.project_manager:
                    self.project_manager.save_project()

    def _on_new_project(self):
        """Обработчик создания нового проекта (переход на другой проект)"""
        self._handle_project_change()

    def _on_project_read(self):
        """Обработчик открытия проекта QGIS"""
        # Проверяем, не является ли это проектом плагина
        if self.project_manager and not self.project_manager.is_project_open():
            # Пытаемся инициализировать из нативного проекта
            if self.project_manager.init_from_native_project():
                # Обновляем состояние меню
                if self.main_toolbar:
                    self.main_toolbar.update_menu_state()

                self._show_project_activated_notification()
                log_info(f"Проект плагина автоматически распознан при открытии")
    
    def _on_project_cleared(self):
        """Обработчик очистки проекта (закрытие через кнопку QGIS)"""
        # Очищаем состояние плагина при закрытии проекта
        if self.project_manager and self.project_manager.is_project_open():
            # Сбрасываем structure_manager
            self.project_manager.structure_manager.project_root = None

            # Закрываем соединение с GeoPackage (освобождает файл в Windows)
            if self.project_manager.project_db:
                self.project_manager.project_db.close()

            # Очищаем состояние проекта
            self.project_manager.current_project = None
            self.project_manager.project_db = None
            self.project_manager.settings = None

            # Обновляем состояние меню
            if self.main_toolbar:
                self.main_toolbar.update_menu_state()

            log_info("Проект закрыт через интерфейс QGIS")
    
    def _on_qgis_closing(self):
        """Обработчик закрытия QGIS"""
        self._handle_project_change()

    def _handle_project_change(self):
        """Общий обработчик изменения проекта с проверкой сохранения"""
        if self.project_manager and self.project_manager.is_project_open():
            self._check_save_before_close()

    def _show_project_activated_notification(self):
        """Показывает уведомление об активации проекта"""
        object_name = "Проект"
        if self.project_manager and self.project_manager.settings:
            object_name = self.project_manager.settings.object_name

        self.iface.messageBar().pushMessage(
            "Daman_QGIS",
            f"Проект '{object_name}' распознан и активирован",
            level=Qgis.Success,
            duration=MESSAGE_SUCCESS_DURATION
        )


    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        # Отключаем обработчики событий
        self._disconnect_project_signals()

        # Закрываем проект если открыт (с проверкой сохранения)
        if self.project_manager:
            self._check_save_before_close()
            self.project_manager.close_project(save_changes=False)

        # Отключаем общие инструменты
        if self.cadnum_search:
            self.cadnum_search.unload()
            self.cadnum_search = None

        # Очищаем менеджеры
        self.project_manager = None
        self.layer_manager = None
        self.version_manager = None
        self.reference_managers = None

        # Удаляем действия из меню QGIS
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)

        # Очищаем main_toolbar
        if self.main_toolbar:
            self.main_toolbar.tools.clear()
            self.main_toolbar.menu_buttons.clear()
            self.main_toolbar = None

        # Удаляем панель инструментов из QGIS
        if self.toolbar:
            main_window = self.iface.mainWindow()
            if hasattr(main_window, 'removeToolBar'):
                main_window.removeToolBar(self.toolbar)  # type: ignore[union-attr]
            self.toolbar.deleteLater()
            self.toolbar = None

        # Сброс синглтонов менеджеров для освобождения ресурсов
        # Это предотвращает утечки памяти и проблемы с Qt при закрытии
        try:
            from Daman_QGIS.managers import (
                reset_async_manager,
                reset_extent_manager,
                reset_project_structure_manager,
                reset_cutting_manager,
                reset_fills_manager
            )
            reset_async_manager()
            reset_extent_manager()
            reset_project_structure_manager()
            reset_cutting_manager()
            reset_fills_manager()
        except Exception:
            pass

        # Защитная очистка: обрабатываем отложенные Qt события
        # Это помогает избежать краша при закрытии QGIS с открытыми таблицами атрибутов
        try:
            from qgis.PyQt.QtCore import QCoreApplication
            QCoreApplication.processEvents()
        except Exception:
            pass
