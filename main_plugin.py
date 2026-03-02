# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Daman_QGIS
                                 A QGIS plugin
 Комплексный инструмент для работы с данными в QGIS
                              -------------------
        begin                : 2024
        copyright            : (C) 2024-2026 Alexander Plahotnyuk
        email                : damanQGIS@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 *   The plugin code is GPL-licensed. However, the server API, reference   *
 *   data, and the "Daman QGIS" trademark are proprietary. Access to the  *
 *   API requires a valid license key. Modified versions must not use the  *
 *   "Daman QGIS" name or trademarks.                                     *
 *                                                                         *
 ***************************************************************************/
"""
# -----------------------------------------------------------------------------
# ВРЕМЕННОЕ ПОДАВЛЕНИЕ ПРЕДУПРЕЖДЕНИЙ (убрать после обновления зависимостей)
# -----------------------------------------------------------------------------
# ezdxf 1.4.3 использует устаревший camelCase API pyparsing (addParseAction и др.)
# pyparsing 3.3.0+ выдает DeprecationWarning для этих методов
# Удалить этот блок когда ezdxf обновится на snake_case API
# Отслеживать: https://github.com/mozman/ezdxf/issues
# -----------------------------------------------------------------------------
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="ezdxf")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pyparsing")
# -----------------------------------------------------------------------------

from typing import Dict, Tuple, Optional, Callable, Any, List
from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, Qt, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QToolBar, QMenu, QMessageBox, QWidget
from qgis.core import QgsProject, Qgis, QgsMessageLog
from qgis.gui import QgisInterface

# Initialize Qt resources from file resources.py
# from .resources import *

import os.path
import sys
import configparser

# ВАЖНО: Инициализируем путь к dependencies ДО импорта внешних зависимостей
# Это позволяет импортировать пакеты из изолированной папки %APPDATA%/QGIS/.../python/dependencies/
from Daman_QGIS.tools.F_4_plagin.submodules.Fsm_4_1_4_pip_installer import PipInstaller
PipInstaller.ensure_dependencies_in_path()

# Import managers (все импорты из managers в одном блоке для избежания циклических зависимостей)
from Daman_QGIS.managers import (
    ProjectManager, LayerManager, VersionManager,
    CadnumSearchManager, registry,
    install_global_exception_hook, uninstall_global_exception_hook,
    track_exception
)

# Import dependency checker (ПОСЛЕ полной загрузки managers)
from Daman_QGIS.tools.F_4_plagin.F_4_1_plugin_diagnostics import F_4_1_PluginDiagnostics

# Import main toolbar
from Daman_QGIS.ui.main_toolbar import MainToolbar

# Import constants
from Daman_QGIS.constants import (
    PLUGIN_NAME, MESSAGE_SHORT_DURATION, MESSAGE_SUCCESS_DURATION,
    PLUGIN_VERSION, HEARTBEAT_INTERVAL_MS
)

# Import logging utilities
from Daman_QGIS.utils import log_info, log_warning, log_error


def _load_tools_config() -> Dict[str, Tuple[str, str]]:
    """
    Загрузка конфигурации инструментов из Base_Functions.json

    Единственный источник истины для регистрации функций на панели.
    Использует FunctionReferenceManager с поддержкой remote загрузки.

    Returns:
        Dict[tool_id, (module_path, class_name)]
    """
    from Daman_QGIS.managers import FunctionReferenceManager

    functions_manager = FunctionReferenceManager()
    tools_config = functions_manager.get_tools_config()

    if not tools_config:
        log_warning("_load_tools_config: Не удалось загрузить функции из Base_Functions.json")
        return {}

    disabled_count = len(functions_manager.get_disabled_functions())

    log_info(f"TOOLS_CONFIG: загружено {len(tools_config)} функций из Base_Functions.json "
             f"(отключено: {disabled_count})")
    return tools_config


# Конфигурация инструментов - заполняется в initGui() после получения JWT токенов
# Mutable: переназначается в _build_full_toolbar() после JWT авторизации
TOOLS_CONFIG: Dict[str, Tuple[str, str]] = {}  # pyright: ignore[reportConstantRedefinition]

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

        # Режим "только активация" -- при отсутствии лицензии
        self._activation_only_mode = False

        # Heartbeat таймер для периодической проверки лицензии
        self._heartbeat_timer = None

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

        # --- Platform Check ---
        if sys.platform != 'win32':
            self.iface.messageBar().pushMessage(
                "Daman QGIS",
                "Плагин поддерживает только Windows",
                level=Qgis.Warning, duration=0
            )
            return

        # --- Session Logging (M_38) --- MUST be first
        from Daman_QGIS.managers._registry import registry
        try:
            session_log = registry.get('M_38')
            session_log.initialize()
        except Exception as e:
            log_warning(f"Daman_QGIS: Session logging init failed: {e}")

        # --- Profile Setup (M_37) ---
        profile_mgr = registry.get('M_37')
        profile_mgr.apply_pending_ini()

        profile_status = profile_mgr.check_and_setup_profile()
        if profile_status in ("setup_done", "sync_done", "wrong_profile"):
            self._profile_only_mode = True
            return  # НЕ инициализировать основной плагин

        self._profile_only_mode = False
        # --- Конец Profile Setup ---

        # Быстрая проверка зависимостей при запуске (краткий лог)
        log_info("Daman_QGIS: Запуск плагина, проверка зависимостей...")
        deps_ok = True
        try:
            deps_ok = F_4_1_PluginDiagnostics.quick_check()
        except Exception as e:
            log_warning(f"Не удалось проверить зависимости: {str(e)}")

        # --- DEPENDENCY GATE: критические зависимости нужны для работы ---
        # Без cryptography Msm_29_2 не может прочитать файл лицензии.
        # Показать диалог активации бессмысленно -- данные не сохранятся.
        if not deps_ok:
            log_warning("Daman_QGIS: Missing dependencies, showing emergency toolbar")
            self._init_managers()
            self._show_emergency_toolbar()
            return

        # Инициализация менеджеров
        self._init_managers()

        # --- LICENSE GATE: JWT токены нужны для загрузки конфигурации ---
        has_license = self._acquire_jwt_tokens()

        if not has_license:
            # Нет лицензии -- принудительно показать диалог активации
            activated = self._show_forced_activation()
            if not activated:
                # Пользователь закрыл без активации -- минимальная панель
                self._show_activation_only_toolbar()
                return
            # Активация успешна -- продолжаем нормальный запуск

        # --- Полная инициализация тулбара ---
        self._build_full_toolbar()

    def _init_nspd_statusbar(self) -> None:
        """Инициализация индикатора авторизации НСПД в statusbar."""
        try:
            from qgis.PyQt.QtWidgets import QLabel
            from Daman_QGIS.managers._registry import registry

            self._nspd_status_label = QLabel("НСПД: --")
            self._nspd_status_label.setStyleSheet(
                "padding: 2px 6px; color: gray; font-size: 9pt;"
            )
            self.iface.statusBarIface().addPermanentWidget(self._nspd_status_label)

            # Подключение сигнала M_40
            nspd_auth = registry.get('M_40')
            if nspd_auth and nspd_auth.is_available():
                self._register_signal(nspd_auth.auth_changed, self._on_nspd_auth_changed)
                # Установить начальный статус
                self._on_nspd_auth_changed(nspd_auth.is_authenticated())
            else:
                self._nspd_status_label.setText("НСПД: н/д")

        except Exception as e:
            log_warning(f"Daman_QGIS: NSPD statusbar init failed: {e}")

    def _on_nspd_auth_changed(self, is_authenticated: bool) -> None:
        """Обработка изменения статуса авторизации НСПД."""
        if not hasattr(self, '_nspd_status_label'):
            return

        if is_authenticated:
            self._nspd_status_label.setText("НСПД: авторизован")
            self._nspd_status_label.setStyleSheet(
                "padding: 2px 6px; color: green; font-weight: bold; font-size: 9pt;"
            )
        else:
            self._nspd_status_label.setText("НСПД: не авторизован")
            self._nspd_status_label.setStyleSheet(
                "padding: 2px 6px; color: gray; font-size: 9pt;"
            )

    def _init_telemetry(self) -> None:
        """Инициализация телеметрии при запуске плагина."""
        try:
            telemetry = registry.get('M_32')

            # Получаем api_key и hardware_id из лицензии
            # ВАЖНО: Сначала initialize(), иначе storage не загрузит данные из файла
            license_mgr = registry.get('M_29')
            license_mgr.initialize()
            api_key = license_mgr.get_api_key()
            hardware_id = license_mgr.get_hardware_id()

            if api_key:
                telemetry.set_uid(api_key, hardware_id)

                # Устанавливаем глобальный перехват исключений
                # ВАЖНО: Должен быть ПОСЛЕ set_uid(), иначе ошибки не отправятся
                install_global_exception_hook()

                # Отправляем событие startup
                telemetry.track_event('startup')
                log_info("Daman_QGIS: Telemetry initialized with global exception hook")
            else:
                log_info("Daman_QGIS: Telemetry skipped (no license)")

        except Exception as e:
            log_warning(f"Daman_QGIS: Telemetry init failed: {e}")

    # === Heartbeat: периодическая проверка статуса лицензии ===

    def _start_heartbeat(self) -> None:
        """Запустить периодическую проверку лицензии на сервере."""
        self._heartbeat_timer = QTimer()
        self._heartbeat_timer.timeout.connect(self._heartbeat_check)
        self._heartbeat_timer.start(HEARTBEAT_INTERVAL_MS)
        log_info("Main: Heartbeat запущен")

    def _heartbeat_check(self) -> None:
        """Проверить статус лицензии на сервере (вызывается по таймеру)."""
        try:
            license_mgr = registry.get('M_29')
            api_key = license_mgr.get_api_key()
            hardware_id = license_mgr.get_hardware_id()

            if not api_key or not hardware_id:
                return

            import time as _time
            import hmac
            import hashlib
            import requests
            from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT

            timestamp = int(_time.time())
            signature = hmac.new(
                api_key.encode('utf-8'),
                f"{hardware_id}|{timestamp}".encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            response = requests.post(
                f"{API_BASE_URL}?action=heartbeat",
                json={
                    "api_key": api_key,
                    "hardware_id": hardware_id,
                    "timestamp": timestamp,
                    "signature": signature
                },
                timeout=API_TIMEOUT
            )

            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'revoked':
                    reason = data.get('reason', 'unknown')
                    log_warning(f"Main: Лицензия отозвана сервером ({reason})")
                    self._on_license_revoked()

        except Exception as e:
            # Graceful degradation: сетевые ошибки не блокируют работу
            log_info(f"Main: Heartbeat пропущен: {e}")

    def _on_license_revoked(self) -> None:
        """Обработка отзыва лицензии сервером."""
        # 1. Остановить heartbeat
        if self._heartbeat_timer:
            self._heartbeat_timer.stop()

        # 2. Очистить токены
        from Daman_QGIS.managers.infrastructure.submodules.Msm_29_4_token_manager import TokenManager
        TokenManager.get_instance().clear_tokens()

        # 3. Очистить кэш данных
        from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
        BaseReferenceLoader.clear_cache()

        # 4. Удалить текущую панель инструментов
        if self.toolbar:
            main_window = self.iface.mainWindow()
            if main_window and hasattr(main_window, 'removeToolBar'):
                main_window.removeToolBar(self.toolbar)
            self.toolbar.deleteLater()
            self.toolbar = None

        # 5. Показать сообщение и переключить на activation toolbar
        self._show_activation_only_toolbar()
        self.iface.messageBar().pushMessage(
            "Daman QGIS",
            "Лицензия деактивирована. Обратитесь к администратору.",
            level=Qgis.Warning, duration=0
        )

    def _check_native_project(self) -> None:
        """Проверка и инициализация нативно открытого проекта плагина"""
        if self.project_manager:
            # Пытаемся инициализировать из нативно открытого проекта
            if self.project_manager.init_from_native_project():
                log_info("Обнаружен и инициализирован нативно открытый проект плагина")
                self._show_project_activated_notification()
    def _init_managers(self) -> None:
        """Инициализация менеджеров плагина"""
        from Daman_QGIS.managers._registry import registry

        # Менеджер проектов
        self.project_manager = ProjectManager(self.iface, self.plugin_dir)
        self.project_manager.plugin_version = self.version

        # Менеджер слоев
        self.layer_manager = LayerManager(self.iface, self.plugin_dir)

        # Менеджер версий
        self.version_manager = VersionManager(self.iface)

        # Менеджер справочных данных (M_4 — фабрика, не синглтон)
        from Daman_QGIS.managers._registry import get_reference_managers
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

    # === License Gate ===

    def _acquire_jwt_tokens(self) -> bool:
        """Инициализация M_29 и получение JWT токенов для API.

        Для лицензированных пользователей: verify() обращается к серверу
        и сохраняет JWT токены в TokenManager.

        Returns:
            True если лицензия активирована И верификация прошла успешно
            False если лицензия отсутствует или верификация не прошла
        """
        license_mgr = registry.get('M_29')
        license_mgr.initialize()

        if not license_mgr.is_activated():
            log_info("Daman_QGIS: No license activated")
            return False

        # Лицензия есть -- verify() получит JWT токены
        verified = license_mgr.verify()
        if not verified:
            log_warning("Daman_QGIS: License verification failed")
            return False

        return True

    def _show_forced_activation(self) -> bool:
        """Принудительный показ модального диалога активации лицензии.

        Вызывается когда лицензия отсутствует. Диалог блокирует выполнение
        до активации или закрытия пользователем.

        Returns:
            True если лицензия успешно активирована
            False если пользователь закрыл диалог без активации
        """
        from Daman_QGIS.tools.F_4_plagin.submodules.Fsm_4_3_1_license_dialog import LicenseDialog

        license_mgr = registry.get('M_29')
        activated = False

        def on_validated(is_valid: bool) -> None:
            nonlocal activated
            if is_valid:
                activated = True

        license_mgr.license_validated.connect(on_validated)

        dialog = LicenseDialog(self.iface, self.iface.mainWindow())
        dialog.setWindowTitle("Daman QGIS - Активация лицензии")
        dialog.exec()

        try:
            license_mgr.license_validated.disconnect(on_validated)
        except TypeError:
            pass  # Сигнал уже отключён

        if activated:
            log_info("Daman_QGIS: License activated via forced dialog")

        return activated

    # === Integrity Verification ===

    # Критические файлы для проверки целостности (ключ -> относительный путь от plugin_dir)
    INTEGRITY_FILES = {
        'main_plugin': 'main_plugin.py',
        'msm_29_3': os.path.join('managers', 'infrastructure', 'submodules', 'Msm_29_3_license_validator.py'),
        'msm_29_4': os.path.join('managers', 'infrastructure', 'submodules', 'Msm_29_4_token_manager.py'),
        'base_ref': os.path.join('database', 'base_reference_loader.py'),
    }

    def _verify_integrity(self) -> None:
        """Проверка целостности критических файлов плагина.

        Сравнивает SHA-256 хеши локальных файлов с эталонными из JWT claims.
        При несовпадении: log_warning + telemetry event (мониторинг).
        НЕ блокирует работу плагина (мягкая проверка).
        """
        import hashlib
        import base64
        import json

        try:
            # Получаем access token из TokenManager
            from Daman_QGIS.managers.infrastructure.submodules.Msm_29_4_token_manager import TokenManager
            token_mgr = TokenManager.get_instance()
            access_token = token_mgr._access_token if token_mgr else None

            if not access_token:
                return  # Нет токена -- пропускаем проверку

            # Декодируем JWT payload (без верификации подписи)
            parts = access_token.split('.')
            if len(parts) != 3:
                return

            payload_b64 = parts[1]
            # Добавляем padding для base64
            payload_b64 += '=' * (4 - len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))

            expected_hashes = payload.get('integrity')
            if not expected_hashes or not isinstance(expected_hashes, dict):
                return  # Сервер не включил integrity claim

            # Вычисляем локальные хеши и сравниваем
            mismatches = []
            for key, rel_path in self.INTEGRITY_FILES.items():
                expected = expected_hashes.get(key)
                if not expected:
                    continue

                # Валидация типа хеша из JWT
                if not isinstance(expected, str):
                    mismatches.append(f"{key}: invalid hash format")
                    continue

                filepath = os.path.join(self.plugin_dir, rel_path)
                if not os.path.exists(filepath):
                    mismatches.append(f"{key}: file missing")
                    continue

                with open(filepath, 'rb') as f:
                    actual = hashlib.sha256(f.read()).hexdigest()

                if actual != expected:
                    mismatches.append(key)

            if mismatches:
                log_warning(f"Daman_QGIS: Integrity check failed for: {', '.join(mismatches)}")
                # Отправляем в телеметрию для мониторинга
                try:
                    track_exception(
                        "main_plugin",
                        RuntimeError(f"Integrity mismatch: {', '.join(mismatches)}"),
                        {"phase": "integrity_check", "files": mismatches}
                    )
                except Exception:
                    pass
            else:
                log_info("Daman_QGIS: Integrity check passed")

        except json.JSONDecodeError as e:
            log_warning(f"Daman_QGIS: Invalid JWT payload in integrity check: {e}")
            try:
                track_exception("main_plugin", e, {"phase": "integrity_jwt_decode"})
            except Exception:
                pass
        except Exception as e:
            # Ошибка проверки не должна блокировать работу
            log_warning(f"Daman_QGIS: Integrity check error: {e}")

    def _show_activation_only_toolbar(self) -> None:
        """Показать минимальную панель с одной кнопкой активации.

        Используется когда пользователь закрыл диалог активации без ввода ключа.
        Кнопка позволяет повторно открыть диалог.
        """
        from qgis.PyQt.QtWidgets import QToolButton

        self._activation_only_mode = True

        self.toolbar = self.iface.addToolBar(PLUGIN_NAME)
        self.toolbar.setObjectName(PLUGIN_NAME)

        btn = QToolButton()
        btn.setText("  Активация лицензии Daman QGIS")
        btn.setIcon(QIcon(':/images/themes/default/mIconCertificate.svg'))
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._register_signal(btn.clicked, self._on_activation_button_clicked)
        self.toolbar.addWidget(btn)

        self.iface.messageBar().pushMessage(
            "Daman QGIS",
            "Для работы плагина необходимо активировать лицензию",
            level=Qgis.Warning, duration=0
        )

    def _on_activation_button_clicked(self) -> None:
        """Обработка клика на кнопку активации в минимальной панели."""
        activated = self._show_forced_activation()
        if activated:
            # Удаляем минимальную панель
            if self.toolbar:
                main_window = self.iface.mainWindow()
                if main_window and hasattr(main_window, 'removeToolBar'):
                    main_window.removeToolBar(self.toolbar)  # type: ignore[union-attr]
                self.toolbar.deleteLater()
                self.toolbar = None

            # Убираем предупреждение
            self.iface.messageBar().clearWidgets()

            self._activation_only_mode = False

            # Строим полную панель
            self._build_full_toolbar()

    def _build_full_toolbar(self) -> None:
        """Построение полной панели инструментов.

        Вызывается после получения JWT токенов (для лицензированных)
        или после успешной активации (для новых пользователей).
        Очищает кэши и загружает конфигурацию с сервера.

        Если Base_Functions.json не загрузился (401, сеть, и т.д.) --
        показывает аварийную панель с F_4_1 и F_4_3.
        """
        global TOOLS_CONFIG

        # Очищаем кэши чтобы загрузка прошла с JWT
        from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
        from Daman_QGIS.managers._registry import reset_reference_managers
        BaseReferenceLoader.clear_cache()
        reset_reference_managers()

        # Загружаем конфигурацию инструментов (теперь с JWT)
        TOOLS_CONFIG = _load_tools_config()  # pyright: ignore[reportConstantRedefinition]

        # Если конфигурация пуста -- аварийная панель
        if not TOOLS_CONFIG:
            log_warning("Daman_QGIS: TOOLS_CONFIG empty, showing emergency toolbar")
            self._show_emergency_toolbar()
            return

        # Проверка целостности критических файлов (anti-tampering)
        self._verify_integrity()

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

        # StatusBar: индикатор авторизации НСПД
        self._init_nspd_statusbar()

        # Инициализация телеметрии
        self._init_telemetry()

        # Heartbeat: периодическая проверка статуса лицензии
        self._start_heartbeat()

        # Deferred profile reference download
        profile_mgr = registry.get('M_37')
        profile_mgr.ensure_reference_profile_applied()

        # Автоматическое обновление профиля при смене версии плагина
        profile_mgr.check_profile_update()

        # Очистка USER CRS реестра (дедупликация по имени)
        try:
            profile_mgr.sync_crs_registry()
        except Exception as e:
            log_warning(f"Daman_QGIS: CRS cleanup failed: {e}")

        # Welcome dialog при первом запуске в Daman_QGIS
        if profile_mgr.is_first_run():
            QTimer.singleShot(2000, profile_mgr.show_first_run_welcome)

    def _show_emergency_toolbar(self) -> None:
        """Аварийная панель с F_4_1 (диагностика) и F_4_3 (лицензия).

        Показывается когда Base_Functions.json не загрузился.
        F_4_1 и F_4_3 НЕ зависят от Base_Functions.json и имеют
        requires_license = False.
        """
        from qgis.PyQt.QtWidgets import QToolButton

        self._activation_only_mode = True

        self.toolbar = self.iface.addToolBar(PLUGIN_NAME)
        self.toolbar.setObjectName(PLUGIN_NAME)

        # Кнопка F_4_1 -- Диагностика / Установка зависимостей
        btn_diag = QToolButton()
        btn_diag.setText("  Диагностика плагина")
        btn_diag.setIcon(QIcon(':/images/themes/default/mActionOptions.svg'))
        btn_diag.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._register_signal(btn_diag.clicked, self._on_emergency_diagnostics)
        self.toolbar.addWidget(btn_diag)

        # Кнопка F_4_3 -- Управление лицензией
        btn_license = QToolButton()
        btn_license.setText("  Управление лицензией")
        btn_license.setIcon(QIcon(':/images/themes/default/mIconCertificate.svg'))
        btn_license.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._register_signal(btn_license.clicked, self._on_emergency_license)
        self.toolbar.addWidget(btn_license)

        # Инициализация телеметрии (лицензия уже есть)
        self._init_telemetry()

        self.iface.messageBar().pushMessage(
            "Daman QGIS",
            "Не удалось загрузить конфигурацию с сервера. "
            "Используйте 'Диагностика плагина' для установки зависимостей. "
            "После установки перезапустите QGIS.",
            level=Qgis.Warning, duration=0
        )

    def _on_emergency_diagnostics(self) -> None:
        """Запуск F_4_1 напрямую (без тулбара)."""
        try:
            from Daman_QGIS.tools.F_4_plagin.submodules.Fsm_4_1_11_diagnostics_dialog import DiagnosticsDialog
            dialog = DiagnosticsDialog(self.iface)
            dialog.exec()
        except Exception as e:
            log_error(f"Daman_QGIS: Failed to open diagnostics dialog: {e}")
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Daman QGIS",
                f"Не удалось открыть диагностику: {e}"
            )

    def _on_emergency_license(self) -> None:
        """Запуск F_4_3 напрямую (без тулбара)."""
        try:
            from Daman_QGIS.tools.F_4_plagin.submodules.Fsm_4_3_1_license_dialog import LicenseDialog
            dialog = LicenseDialog(self.iface, self.iface.mainWindow())
            dialog.exec()
        except Exception as e:
            log_error(f"Daman_QGIS: Failed to open license dialog: {e}")
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Daman QGIS",
                f"Не удалось открыть управление лицензией: {e}"
            )

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

    # Инструменты скрытые из меню (вызываются только программно)
    HIDDEN_TOOLS = set()

    def _register_tools(self) -> None:
        """Регистрация всех доступных инструментов"""
        registered_count = 0
        failed_tools = []

        # Автоматическая регистрация инструментов из конфигурации
        for tool_id, (module_path, class_name) in TOOLS_CONFIG.items():
            # Пропускаем инструменты скрытые из меню
            if tool_id in self.HIDDEN_TOOLS:
                continue
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
                # Отправляем в телеметрию - ошибка загрузки модуля критична
                track_exception("main_plugin", e, {"tool_id": tool_id, "phase": "import"})

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
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard,
                QMessageBox.StandardButton.Save
            )
            
            if reply == QMessageBox.StandardButton.Save:
                # Сохраняем проект
                if self.project_manager:
                    self.project_manager.save_project()

    def _on_new_project(self):
        """Обработчик создания нового проекта (переход на другой проект)"""
        self._handle_project_change()

    def _on_project_read(self):
        """Обработчик открытия проекта QGIS"""
        try:
            # Проверяем, не является ли это проектом плагина
            if self.project_manager and not self.project_manager.is_project_open():
                # Пытаемся инициализировать из нативного проекта
                if self.project_manager.init_from_native_project():
                    # Обновляем состояние меню
                    if self.main_toolbar:
                        self.main_toolbar.update_menu_state()

                    self._show_project_activated_notification()
                    log_info("Проект плагина автоматически распознан при открытии")
        except Exception as e:
            log_error(f"_on_project_read: Ошибка при проверке проекта: {e}")
    
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
        # Profile-only mode: ничего не было инициализировано
        if getattr(self, '_profile_only_mode', False):
            from Daman_QGIS.managers._registry import registry
            registry.reset('M_37')
            return

        # Activation-only mode: только минимальная панель с кнопкой
        if getattr(self, '_activation_only_mode', False):
            if self.toolbar:
                main_window = self.iface.mainWindow()
                if main_window and hasattr(main_window, 'removeToolBar'):
                    main_window.removeToolBar(self.toolbar)  # type: ignore[union-attr]
                self.toolbar.deleteLater()
                self.toolbar = None
            return

        # Остановить heartbeat таймер
        if self._heartbeat_timer:
            self._heartbeat_timer.stop()
            self._heartbeat_timer = None

        # Flush телеметрии перед выгрузкой (синхронно, до 2 сек)
        try:
            from Daman_QGIS.managers._registry import registry
            telemetry = registry.get('M_32')
            telemetry.track_event('shutdown')
            telemetry.flush_sync(timeout=2.0)
        except Exception:
            pass  # Молча игнорируем ошибки телеметрии при выгрузке

        # Восстанавливаем оригинальные exception hooks
        try:
            uninstall_global_exception_hook()
        except Exception:
            pass

        # Shutdown session logging (M_38) — ПОСЛЕ телеметрии, чтобы shutdown-сообщения записались
        try:
            from Daman_QGIS.managers._registry import registry
            session_log = registry.get('M_38')
            session_log.shutdown()
        except Exception:
            pass

        # Очистка НСПД авторизации и statusbar widget
        try:
            from Daman_QGIS.managers._registry import registry
            nspd_auth = registry.get('M_40')
            if nspd_auth:
                nspd_auth.cleanup()
        except Exception:
            pass
        if hasattr(self, '_nspd_status_label') and self._nspd_status_label:
            self.iface.statusBarIface().removeWidget(self._nspd_status_label)
            self._nspd_status_label = None

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
            registry.reset('M_17')
            registry.reset('M_18')
            registry.reset('M_19')
            registry.reset('M_26')
            registry.reset('M_25')
            registry.reset('M_37')
        except Exception:
            pass

        # Защитная очистка: обрабатываем отложенные Qt события
        # Это помогает избежать краша при закрытии QGIS с открытыми таблицами атрибутов
        try:
            from qgis.PyQt.QtCore import QCoreApplication
            QCoreApplication.processEvents()
        except Exception:
            pass
