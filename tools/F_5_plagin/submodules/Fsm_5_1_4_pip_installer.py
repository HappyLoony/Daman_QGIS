# -*- coding: utf-8 -*-
"""
Fsm_5_1_4_PipInstaller - Установка Python пакетов через pip

Отвечает за установку Python библиотек в изолированную директорию плагина.

ВАЖНО: Используется --target вместо --user для изоляции зависимостей.
Путь: %APPDATA%/QGIS/QGIS3/profiles/default/python/dependencies/
Преимущество: Не засоряет user site-packages, можно удалить всё одним действием.
"""

import sys
import os
import subprocess
import threading
import time
from queue import Queue, Empty
from typing import Dict, List, Callable, Optional
from pathlib import Path

from qgis.core import Qgis, QgsApplication
from qgis.PyQt.QtCore import QThread
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error


class PipInstaller:
    """Установка Python пакетов через pip в изолированную директорию"""

    # Путь к изолированной папке dependencies (относительно QGIS profile)
    DEPENDENCIES_FOLDER = "dependencies"

    # Timeout для установки одного пакета (секунды)
    # 120 секунд достаточно для большинства пакетов, включая большие как qgis-stubs
    INSTALL_TIMEOUT = 120

    @staticmethod
    def get_dependencies_path() -> str:
        """
        Получить путь к изолированной папке dependencies.

        Путь: %APPDATA%/QGIS/QGIS3/profiles/default/python/dependencies/

        Returns:
            str: Абсолютный путь к папке dependencies
        """
        # QgsApplication.qgisSettingsDirPath() возвращает путь к профилю QGIS
        # Например: C:/Users/Username/AppData/Roaming/QGIS/QGIS3/profiles/default/
        qgis_settings_dir = QgsApplication.qgisSettingsDirPath().replace("/", os.path.sep)
        dependencies_path = os.path.join(qgis_settings_dir, "python", PipInstaller.DEPENDENCIES_FOLDER)
        return dependencies_path

    @staticmethod
    def ensure_dependencies_in_path() -> str:
        """
        Добавить путь dependencies в sys.path и PYTHONPATH если его там нет.

        Должен вызываться при старте плагина ДО импорта зависимостей.

        Returns:
            str: Путь к папке dependencies
        """
        dependencies_path = PipInstaller.get_dependencies_path()

        # Создаём папку если не существует
        os.makedirs(dependencies_path, exist_ok=True)

        # Добавляем в sys.path (в начало для приоритета)
        if dependencies_path not in sys.path:
            sys.path.insert(0, dependencies_path)
            log_info(f"F_5_1: Добавлен путь dependencies в sys.path: {dependencies_path}")

        # Добавляем в PYTHONPATH для subprocess
        pythonpath = os.environ.get("PYTHONPATH", "")
        if dependencies_path not in pythonpath:
            os.environ["PYTHONPATH"] = dependencies_path + os.pathsep + pythonpath

        # Очищаем кэш импортера для поиска новых модулей
        sys.path_importer_cache.clear()

        return dependencies_path

    @staticmethod
    def cleanup_old_dist_info(package_name: str, keep_version: Optional[str] = None) -> int:
        """
        Удаление старых dist-info папок для пакета после обновления.

        Args:
            package_name: Имя пакета (например 'pytest')
            keep_version: Версия которую нужно оставить. Если None - оставляет самую новую.

        Returns:
            int: Количество удалённых папок
        """
        import shutil
        try:
            from packaging.version import parse as parse_version
        except ImportError:
            parse_version = None

        dependencies_path = PipInstaller.get_dependencies_path()
        if not os.path.exists(dependencies_path):
            return 0

        # Нормализуем имя пакета
        normalized_name = package_name.lower().replace('-', '_')

        # Собираем все dist-info для этого пакета
        dist_infos = []
        for item in os.listdir(dependencies_path):
            if item.endswith('.dist-info'):
                parts = item[:-10].rsplit('-', 1)  # убираем .dist-info
                if len(parts) == 2:
                    dist_name = parts[0].lower().replace('-', '_')
                    dist_version = parts[1]
                    if dist_name == normalized_name:
                        dist_infos.append((item, dist_version))

        if len(dist_infos) <= 1:
            return 0  # Нечего чистить

        # Определяем какую версию оставить
        if keep_version is None:
            # Оставляем самую новую
            if parse_version:
                dist_infos.sort(key=lambda x: parse_version(x[1]), reverse=True)
            else:
                dist_infos.sort(key=lambda x: x[1], reverse=True)
            keep_version = dist_infos[0][1]

        # Удаляем старые
        removed = 0
        for dist_info_name, version in dist_infos:
            if version != keep_version:
                dist_info_path = os.path.join(dependencies_path, dist_info_name)
                try:
                    shutil.rmtree(dist_info_path)
                    log_info(f"F_5_1: Удалена старая версия {dist_info_name}")
                    removed += 1
                except Exception as e:
                    log_warning(f"F_5_1: Не удалось удалить {dist_info_name}: {e}")

        return removed

    def __init__(self, packages: Dict[str, Dict], user_site: Optional[str] = None, progress_callback: Optional[Callable] = None):
        """
        Инициализация установщика

        Args:
            packages: Словарь пакетов для установки {имя: {install_cmd, ...}}
            user_site: DEPRECATED - игнорируется, используется get_dependencies_path()
            progress_callback: Функция обратного вызова для отчета о прогрессе
        """
        self.packages = packages
        # Используем изолированную папку dependencies вместо user_site
        self.dependencies_path = self.get_dependencies_path()
        self.progress_callback = progress_callback
        self.python_exe = self.get_python_executable()

    def emit_progress(self, message: str):
        """Отправить сообщение о прогрессе"""
        if self.progress_callback:
            self.progress_callback(message)

    @staticmethod
    def get_python_executable() -> str:
        """
        Находит правильный путь к python.exe в установке QGIS

        Returns:
            str: Путь к python.exe или sys.executable если не найден
        """
        current_exe = sys.executable

        # Если это уже python.exe - используем его
        if 'python' in os.path.basename(current_exe).lower():
            log_info(f"F_5_1: Используется текущий Python: {current_exe}")
            return current_exe

        log_info(f"F_5_1: Поиск python.exe (текущий исполняемый: {current_exe})")

        # Получаем директорию bin где находится QGIS
        bin_dir = os.path.dirname(current_exe)

        # Список возможных имен Python
        python_names = ['python.exe', 'python3.exe', 'python3.9.exe',
                       'python3.10.exe', 'python3.11.exe', 'python3.12.exe']

        # Ищем python.exe в той же папке bin
        for python_name in python_names:
            python_path = os.path.join(bin_dir, python_name)
            if os.path.exists(python_path):
                log_info(f"F_5_1: Найден Python в bin: {python_path}")
                return python_path

        # Если не нашли в bin, проверяем в apps/Python*
        qgis_root = os.path.dirname(bin_dir)
        apps_dir = os.path.join(qgis_root, 'apps')
        if os.path.exists(apps_dir):
            for folder in os.listdir(apps_dir):
                if folder.lower().startswith('python'):
                    python_dir = os.path.join(apps_dir, folder)
                    for python_name in python_names:
                        python_path = os.path.join(python_dir, python_name)
                        if os.path.exists(python_path):
                            log_info(f"F_5_1: Найден Python в apps: {python_path}")
                            return python_path

        # Проверяем в Program Files для standalone установок
        if sys.platform == 'win32':
            program_files = [
                os.environ.get('ProgramFiles', 'C:\\Program Files'),
                os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)')
            ]

            for pf in program_files:
                qgis_dirs = Path(pf).glob('QGIS*') if Path(pf).exists() else []
                for qgis_dir in qgis_dirs:
                    if qgis_dir.is_dir():
                        for python_name in python_names:
                            python_path = qgis_dir / 'bin' / python_name
                            if python_path.exists():
                                log_info(f"F_5_1: Найден Python в Program Files: {python_path}")
                                return str(python_path)

        # Последняя попытка - проверить переменную окружения PYTHONHOME
        python_home = os.environ.get('PYTHONHOME')
        if python_home:
            for python_name in python_names:
                python_path = os.path.join(python_home, python_name)
                if os.path.exists(python_path):
                    log_info(f"F_5_1: Найден Python через PYTHONHOME: {python_path}")
                    return python_path

        # Не удалось найти python.exe - возвращаем sys.executable
        log_warning(f"F_5_1: Python.exe не найден, используется sys.executable: {current_exe}")
        return current_exe

    def install_package(self, package_name: str, package_spec: str) -> bool:
        """
        Установка одного пакета через pip в изолированную папку dependencies

        Args:
            package_name: Имя пакета
            package_spec: Спецификация пакета (например "ezdxf>=1.4.2")

        Returns:
            bool: True если установка успешна
        """
        self.emit_progress(f"Устанавливаю {package_name}...")

        # Команда для установки в изолированную директорию через --target
        # --target устанавливает пакеты в указанную папку (изолированно от системы)
        # --upgrade обновляет если уже установлен
        # --no-warn-script-location подавляет предупреждения о PATH для скриптов
        cmd = [
            self.python_exe, "-m", "pip", "install",
            "--target", self.dependencies_path,  # Изолированная директория
            "--upgrade",  # Обновить если уже установлен
            "--no-warn-script-location",  # Не предупреждать о скриптах
            package_spec
        ]

        self.emit_progress(f"Выполняю: {' '.join(cmd)}")
        self.emit_progress(f"Timeout: {self.INSTALL_TIMEOUT} сек")

        # Настройка для скрытия консольного окна на Windows
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        # Запускаем процесс
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=os.environ.copy(),
            startupinfo=startupinfo
        )

        # Список для сбора вывода из потока
        output_lines = []
        # Очередь для передачи сообщений между потоками
        message_queue: Queue = Queue()

        def read_output():
            """Читает вывод процесса в отдельном потоке"""
            if process.stdout:
                for line in process.stdout:
                    line = line.strip()
                    if line:
                        output_lines.append(line)
                        message_queue.put(line)

        try:
            # Запускаем чтение вывода в отдельном потоке
            reader_thread = threading.Thread(target=read_output, daemon=True)
            reader_thread.start()

            # Ждем завершения с периодической проверкой очереди сообщений
            start_time = time.time()
            while True:
                # Проверяем очередь сообщений и отправляем их
                try:
                    while True:
                        msg = message_queue.get_nowait()
                        self.emit_progress(msg)
                except Empty:
                    pass

                # Проверяем завершился ли процесс
                retcode = process.poll()
                if retcode is not None:
                    break

                # Проверяем timeout
                elapsed = time.time() - start_time
                if elapsed > self.INSTALL_TIMEOUT:
                    self.emit_progress(f"Timeout ({self.INSTALL_TIMEOUT} сек) - прерываю установку {package_name}")
                    process.kill()
                    process.wait()
                    log_error(f"F_5_1: Timeout при установке {package_name}")
                    return False

                # Небольшая пауза чтобы не грузить CPU
                QThread.msleep(100)

            # Ждем завершения потока чтения
            reader_thread.join(timeout=2.0)

            # Забираем оставшиеся сообщения из очереди
            try:
                while True:
                    msg = message_queue.get_nowait()
                    self.emit_progress(msg)
            except Empty:
                pass

            if process.returncode != 0:
                self.emit_progress(f"X Ошибка установки {package_name} (код: {process.returncode})")
                return False
            else:
                self.emit_progress(f"OK {package_name} установлен успешно")
                # Очищаем старые dist-info после успешного обновления
                removed = self.cleanup_old_dist_info(package_name)
                if removed > 0:
                    self.emit_progress(f"   Удалено {removed} устаревших версий")
                return True
        finally:
            # Явно закрываем stdout для предотвращения ResourceWarning
            if process.stdout:
                process.stdout.close()

    def install_all(self) -> List[str]:
        """
        Установка всех пакетов в изолированную папку dependencies

        Returns:
            list: Список ошибок (пустой если все успешно)
        """
        errors = []

        # Создаем директорию dependencies если нужно
        os.makedirs(self.dependencies_path, exist_ok=True)

        self.emit_progress(f"Используется Python: {self.python_exe}")
        self.emit_progress(f"Путь установки (изолированный): {self.dependencies_path}")

        # Устанавливаем каждый пакет
        for package_name, package_info in self.packages.items():
            # Формируем спецификацию пакета
            install_cmd = package_info.get('install_cmd', f'python -m pip install {package_name}')
            package_spec = install_cmd.split()[-1]  # Получаем спецификацию пакета

            if not self.install_package(package_name, package_spec):
                errors.append(f"Ошибка при установке {package_name}")

        # Добавляем путь dependencies в sys.path и PYTHONPATH
        self.ensure_dependencies_in_path()
        self.emit_progress(f"Путь {self.dependencies_path} добавлен в sys.path")

        return errors
