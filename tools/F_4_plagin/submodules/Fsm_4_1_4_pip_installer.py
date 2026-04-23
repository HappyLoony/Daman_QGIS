# -*- coding: utf-8 -*-
"""
Fsm_4_1_4_PipInstaller - Установка Python пакетов через pip

Отвечает за установку Python библиотек в изолированную директорию плагина.

ВАЖНО: Используется --target вместо --user для изоляции зависимостей.
Путь: %APPDATA%/QGIS/QGIS3/profiles/default/python/dependencies/
Преимущество: Не засоряет user site-packages, можно удалить всё одним действием.

Обработка заблокированных файлов (Windows):
При обновлении пакетов с нативными расширениями (.pyd/.dll), загруженными в память QGIS,
Windows блокирует их удаление/перезапись. Используется двухфазная стратегия:
  Фаза 1 (установка): pip ставит в staging-папку, затем файлы копируются в dependencies/.
           Заблокированные файлы обходятся через os.rename(old -> .old) + копирование нового.
  Фаза 2 (очистка):   При следующем запуске ensure_dependencies_in_path() удаляет *.pyd.old
"""

import sys
import os
import glob
import shutil
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

    # Staging-папка для двухфазной установки (обход блокировки .pyd на Windows)
    STAGING_FOLDER = "dependencies_staging"

    # Папка с pre-downloaded wheels (заполняется инсталлятором Daman_Install).
    # При наличии используется как приоритетный источник через pip --find-links.
    # PyPI остаётся fallback для пакетов, отсутствующих локально.
    WHEELS_FOLDER = "wheels"

    # Суффикс для переименованных заблокированных файлов
    LOCKED_FILE_SUFFIX = ".old"

    # Расширения нативных файлов, которые могут быть заблокированы Windows
    NATIVE_EXTENSIONS = ('.pyd', '.dll', '.so', '.dylib')

    # Timeout для установки одного пакета (секунды).
    # 300 секунд — запас для медленных соединений (без VPN) и крупных пакетов
    # (cryptography, lxml, pypdf с нативными модулями).
    INSTALL_TIMEOUT = 300

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
    def get_staging_path() -> str:
        """
        Получить путь к staging-папке для двухфазной установки.

        Staging используется чтобы pip не падал при заблокированных .pyd файлах.
        pip ставит сюда, затем файлы переносятся в dependencies/.

        Returns:
            str: Абсолютный путь к папке staging
        """
        qgis_settings_dir = QgsApplication.qgisSettingsDirPath().replace("/", os.path.sep)
        staging_path = os.path.join(qgis_settings_dir, "python", PipInstaller.STAGING_FOLDER)
        return staging_path

    @staticmethod
    def get_wheels_path() -> str:
        """
        Получить путь к папке с pre-downloaded wheels.

        Папка заполняется инсталлятором Daman_Install при установке QGIS.
        Путь: %APPDATA%/QGIS/QGIS3/profiles/<profile>/python/wheels/

        Returns:
            str: Абсолютный путь к папке wheels (может не существовать)
        """
        qgis_settings_dir = QgsApplication.qgisSettingsDirPath().replace("/", os.path.sep)
        wheels_path = os.path.join(qgis_settings_dir, "python", PipInstaller.WHEELS_FOLDER)
        return wheels_path

    @staticmethod
    def has_local_wheels() -> bool:
        """
        Проверить наличие папки wheels с pre-downloaded .whl файлами.

        Returns:
            bool: True если папка существует и содержит хотя бы один *.whl
        """
        wheels_path = PipInstaller.get_wheels_path()
        if not os.path.isdir(wheels_path):
            return False
        try:
            for entry in os.listdir(wheels_path):
                if entry.lower().endswith(".whl"):
                    return True
        except OSError:
            return False
        return False

    @staticmethod
    def cleanup_stale_files() -> int:
        """
        Удаление .old файлов, оставшихся после обновления заблокированных пакетов.

        Вызывается при старте плагина (из ensure_dependencies_in_path),
        когда заблокированные файлы уже освобождены после перезапуска QGIS.

        Также удаляет staging-папку если она осталась от прерванной установки.

        Returns:
            int: Количество удалённых файлов
        """
        dependencies_path = PipInstaller.get_dependencies_path()
        staging_path = PipInstaller.get_staging_path()
        removed = 0

        # 1. Удаляем *.old файлы в dependencies (рекурсивно)
        if os.path.exists(dependencies_path):
            pattern = os.path.join(dependencies_path, "**", f"*{PipInstaller.LOCKED_FILE_SUFFIX}")
            for old_file in glob.glob(pattern, recursive=True):
                try:
                    os.remove(old_file)
                    removed += 1
                except OSError as e:
                    # Файл всё ещё заблокирован - оставляем до следующего раза
                    log_warning(f"Fsm_4_1_4: Не удалось удалить {old_file}: {e}")

        # 2. Удаляем staging-папку если осталась
        if os.path.exists(staging_path):
            try:
                shutil.rmtree(staging_path)
                log_info("Fsm_4_1_4: Удалена staging-папка от предыдущей установки")
            except OSError as e:
                log_warning(f"Fsm_4_1_4: Не удалось удалить staging-папку: {e}")

        if removed > 0:
            log_info(f"Fsm_4_1_4: Удалено {removed} устаревших .old файлов")

        return removed

    @staticmethod
    def has_pending_restart() -> bool:
        """
        Проверка наличия .old файлов в dependencies (ожидается перезапуск QGIS).

        Если .old файлы существуют, значит при предыдущей установке некоторые файлы
        были обновлены через rename-трюк и полное обновление произойдёт после перезапуска.

        Returns:
            bool: True если есть .old файлы (перезапуск необходим)
        """
        dependencies_path = PipInstaller.get_dependencies_path()
        if not os.path.exists(dependencies_path):
            return False

        pattern = os.path.join(dependencies_path, "**", f"*{PipInstaller.LOCKED_FILE_SUFFIX}")
        old_files = glob.glob(pattern, recursive=True)
        return len(old_files) > 0

    @staticmethod
    def count_pending_restart_files() -> int:
        """
        Подсчёт .old файлов в dependencies (ожидающих очистки после перезапуска).

        Returns:
            int: Количество .old файлов
        """
        dependencies_path = PipInstaller.get_dependencies_path()
        if not os.path.exists(dependencies_path):
            return 0

        pattern = os.path.join(dependencies_path, "**", f"*{PipInstaller.LOCKED_FILE_SUFFIX}")
        return len(glob.glob(pattern, recursive=True))

    @staticmethod
    def _merge_staging_to_target(staging_path: str, target_path: str,
                                 progress_callback: Optional[Callable] = None) -> dict:
        """
        Перенос файлов из staging-папки в target (dependencies/).

        Для заблокированных файлов (.pyd, .dll) использует rename-трюк:
        Windows позволяет переименовать загруженный файл, хотя удалить нельзя.
        Старый файл переименовывается в .old, новый копируется на его место.

        Args:
            staging_path: Путь к staging-папке (источник)
            target_path: Путь к dependencies/ (цель)
            progress_callback: Функция для вывода прогресса

        Returns:
            dict: {
                'copied': int,      # Скопированных файлов
                'renamed': int,     # Файлов обойдённых через rename
                'failed': list,     # Список ошибок
                'needs_restart': bool  # Нужен ли перезапуск QGIS
            }
        """
        result = {'copied': 0, 'renamed': 0, 'failed': [], 'needs_restart': False}

        def _emit(msg: str):
            if progress_callback:
                progress_callback(msg)

        for root, dirs, files in os.walk(staging_path):
            # Вычисляем относительный путь от staging
            rel_root = os.path.relpath(root, staging_path)
            dest_root = os.path.join(target_path, rel_root) if rel_root != '.' else target_path

            # Создаём директории
            os.makedirs(dest_root, exist_ok=True)

            for filename in files:
                src_file = os.path.join(root, filename)
                dst_file = os.path.join(dest_root, filename)

                try:
                    # Пробуем обычное копирование с перезаписью
                    shutil.copy2(src_file, dst_file)
                    result['copied'] += 1

                except PermissionError:
                    # Файл заблокирован - пробуем rename-трюк
                    old_file = dst_file + PipInstaller.LOCKED_FILE_SUFFIX
                    try:
                        # Удаляем предыдущий .old если есть
                        if os.path.exists(old_file):
                            try:
                                os.remove(old_file)
                            except OSError:
                                pass

                        # Переименовываем заблокированный файл (Windows разрешает rename)
                        os.rename(dst_file, old_file)

                        # Копируем новый файл на место старого
                        shutil.copy2(src_file, dst_file)

                        result['renamed'] += 1
                        result['needs_restart'] = True
                        _emit(f"   Файл {filename} заблокирован - обновлён через rename")

                    except OSError as e:
                        # Rename тоже не удался - критическая ошибка для этого файла
                        error_msg = f"Не удалось обновить {filename}: {e}"
                        result['failed'].append(error_msg)
                        _emit(f"   {error_msg}")

                except OSError as e:
                    error_msg = f"Ошибка копирования {filename}: {e}"
                    result['failed'].append(error_msg)
                    _emit(f"   {error_msg}")

        return result

    @staticmethod
    def ensure_dependencies_in_path() -> str:
        """
        Добавить путь dependencies в sys.path и PYTHONPATH если его там нет.

        Должен вызываться при старте плагина ДО импорта зависимостей.

        Returns:
            str: Путь к папке dependencies
        """
        dependencies_path = PipInstaller.get_dependencies_path()

        # Очищаем .old файлы от предыдущей установки (Фаза 2)
        # Безопасно: при первом запуске файлов просто нет
        PipInstaller.cleanup_stale_files()

        # Создаём папку если не существует
        os.makedirs(dependencies_path, exist_ok=True)

        # Добавляем в sys.path (в начало для приоритета)
        if dependencies_path not in sys.path:
            sys.path.insert(0, dependencies_path)

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
                    log_info(f"F_4_1: Удалена старая версия {dist_info_name}")
                    removed += 1
                except Exception as e:
                    log_warning(f"F_4_1: Не удалось удалить {dist_info_name}: {e}")

        return removed

    def __init__(self, packages: Dict[str, Dict], progress_callback: Optional[Callable] = None):
        """
        Инициализация установщика

        Args:
            packages: Словарь пакетов для установки {имя: {install_cmd, ...}}
            progress_callback: Функция обратного вызова для отчета о прогрессе
        """
        self.packages = packages
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
            log_info(f"F_4_1: Используется текущий Python: {current_exe}")
            return current_exe

        log_info(f"F_4_1: Поиск python.exe (текущий исполняемый: {current_exe})")

        # Получаем директорию bin где находится QGIS
        bin_dir = os.path.dirname(current_exe)

        # Список возможных имен Python
        python_names = ['python.exe', 'python3.exe', 'python3.9.exe',
                       'python3.10.exe', 'python3.11.exe', 'python3.12.exe']

        # Ищем python.exe в той же папке bin
        for python_name in python_names:
            python_path = os.path.join(bin_dir, python_name)
            if os.path.exists(python_path):
                log_info(f"F_4_1: Найден Python в bin: {python_path}")
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
                            log_info(f"F_4_1: Найден Python в apps: {python_path}")
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
                                log_info(f"F_4_1: Найден Python в Program Files: {python_path}")
                                return str(python_path)

        # Последняя попытка - проверить переменную окружения PYTHONHOME
        python_home = os.environ.get('PYTHONHOME')
        if python_home:
            for python_name in python_names:
                python_path = os.path.join(python_home, python_name)
                if os.path.exists(python_path):
                    log_info(f"F_4_1: Найден Python через PYTHONHOME: {python_path}")
                    return python_path

        # Не удалось найти python.exe - возвращаем sys.executable
        log_warning(f"F_4_1: Python.exe не найден, используется sys.executable: {current_exe}")
        return current_exe

    def _run_pip(self, package_name: str, package_spec: str,
                 target_path: str, log_as_warning: bool = False) -> bool:
        """
        Запуск pip install для одного пакета.

        Args:
            package_name: Имя пакета (для логов)
            package_spec: Спецификация пакета (например "ezdxf>=1.4.2")
            target_path: Путь для --target (dependencies/ или staging/)
            log_as_warning: True для Phase 1 (ожидаемая PermissionError),
                           False для Phase 2/staging (реальная ошибка -> CRITICAL)

        Returns:
            bool: True если pip завершился успешно
        """
        cmd = [
            self.python_exe, "-m", "pip", "install",
            "--target", target_path,
            "--upgrade",
            "--no-warn-script-location",
        ]

        # Приоритет локальному кэшу wheels (если заполнен Daman_Install).
        # --find-links указывается ПЕРВЫМ источником; PyPI остаётся fallback
        # через стандартный --index-url (pip по умолчанию его опрашивает).
        wheels_path = self.get_wheels_path()
        if self.has_local_wheels():
            cmd.extend(["--find-links", wheels_path])
            self.emit_progress(
                f"Fsm_4_1_4: используется локальный кэш wheels: {wheels_path}"
            )
        else:
            self.emit_progress(
                f"Fsm_4_1_4: локальный кэш wheels не найден, загружается из PyPI"
            )

        cmd.append(package_spec)

        self.emit_progress(f"Выполняю: {' '.join(cmd)}")
        self.emit_progress(f"Timeout: {self.INSTALL_TIMEOUT} сек")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=os.environ.copy(),
            startupinfo=self._get_startupinfo()
        )

        output_lines = []
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
            reader_thread = threading.Thread(target=read_output, daemon=True)
            reader_thread.start()

            start_time = time.time()
            while True:
                try:
                    while True:
                        msg = message_queue.get_nowait()
                        self.emit_progress(msg)
                except Empty:
                    pass

                retcode = process.poll()
                if retcode is not None:
                    break

                elapsed = time.time() - start_time
                if elapsed > self.INSTALL_TIMEOUT:
                    self.emit_progress(
                        f"Timeout ({self.INSTALL_TIMEOUT} сек) - прерываю установку {package_name}"
                    )
                    process.kill()
                    process.wait()
                    log_error(f"Fsm_4_1_4: Timeout при установке {package_name}")
                    return False

                QThread.msleep(100)

            reader_thread.join(timeout=2.0)

            try:
                while True:
                    msg = message_queue.get_nowait()
                    self.emit_progress(msg)
            except Empty:
                pass

            if process.returncode != 0:
                # Логируем вывод pip при ошибке для диагностики
                last_lines = output_lines[-10:] if output_lines else ["(нет вывода)"]
                msg = (
                    f"Fsm_4_1_4: pip install {package_name} failed "
                    f"(returncode={process.returncode}): "
                    f"{' | '.join(last_lines)}"
                )
                # Phase 1 (прямая установка) — PermissionError ожидаема, есть fallback
                # Phase 2 (staging) — реальная ошибка, CRITICAL + телеметрия
                if log_as_warning:
                    log_warning(msg)
                else:
                    log_error(msg)
                return False

            return True

        finally:
            if process.stdout:
                process.stdout.close()

    def install_package(self, package_name: str, package_spec: str) -> bool:
        """
        Установка одного пакета через pip в изолированную папку dependencies.

        Стратегия:
        1. Пробуем прямую установку в dependencies/ (быстрый путь)
        2. Если pip падает (PermissionError на .pyd/.dll) - используем staging:
           a. pip install --target staging/
           b. Переносим файлы из staging в dependencies/
           c. Заблокированные файлы обходим через rename (.old)
        3. После staging-установки сообщаем о необходимости перезапуска

        Args:
            package_name: Имя пакета
            package_spec: Спецификация пакета (например "ezdxf>=1.4.2")

        Returns:
            bool: True если установка успешна (может требовать перезапуск)
        """
        self.emit_progress(f"Устанавливаю {package_name}...")

        # --- Фаза 1: Прямая установка ---
        # log_as_warning=True: PermissionError на .pyd/.dll ожидаема, есть Phase 2
        success = self._run_pip(package_name, package_spec, self.dependencies_path, log_as_warning=True)

        if success:
            self.emit_progress(f"OK {package_name} установлен успешно")
            removed = self.cleanup_old_dist_info(package_name)
            if removed > 0:
                self.emit_progress(f"   Удалено {removed} устаревших версий")
            return True

        # --- Фаза 2: Staging-установка (обход заблокированных файлов) ---
        self.emit_progress(
            f"Прямая установка {package_name} не удалась, "
            f"пробую через staging (обход блокировки файлов)..."
        )
        log_info(f"Fsm_4_1_4: Переход на staging-установку для {package_name}")

        staging_path = self.get_staging_path()

        # Очищаем staging перед использованием
        if os.path.exists(staging_path):
            try:
                shutil.rmtree(staging_path)
            except OSError as e:
                log_warning(f"Fsm_4_1_4: Не удалось очистить staging: {e}")

        os.makedirs(staging_path, exist_ok=True)

        # Устанавливаем в staging
        staging_success = self._run_pip(package_name, package_spec, staging_path)

        if not staging_success:
            self.emit_progress(f"X Ошибка установки {package_name} (staging тоже не удался)")
            log_error(f"Fsm_4_1_4: Staging-установка {package_name} не удалась")
            # Чистим staging
            if os.path.exists(staging_path):
                shutil.rmtree(staging_path, ignore_errors=True)
            return False

        # Переносим из staging в dependencies
        self.emit_progress(f"Перенос {package_name} из staging в dependencies...")
        merge_result = self._merge_staging_to_target(
            staging_path, self.dependencies_path,
            progress_callback=self.progress_callback
        )

        # Чистим staging
        if os.path.exists(staging_path):
            shutil.rmtree(staging_path, ignore_errors=True)

        # Анализируем результат
        if merge_result['failed']:
            failed_count = len(merge_result['failed'])
            self.emit_progress(
                f"X {package_name}: {failed_count} файлов не удалось обновить"
            )
            log_error(
                f"Fsm_4_1_4: {package_name} - не удалось перенести файлы: "
                f"{merge_result['failed']}"
            )
            return False

        # Успех
        msg_parts = [f"OK {package_name} установлен"]
        if merge_result['renamed'] > 0:
            msg_parts.append(
                f"({merge_result['renamed']} файлов обновлены через rename, "
                f"требуется перезапуск QGIS)"
            )
        self.emit_progress(" ".join(msg_parts))

        if merge_result['needs_restart']:
            log_info(
                f"Fsm_4_1_4: {package_name} установлен через staging, "
                f"перезапуск QGIS для полного применения"
            )

        # Очищаем старые dist-info
        removed = self.cleanup_old_dist_info(package_name)
        if removed > 0:
            self.emit_progress(f"   Удалено {removed} устаревших версий")

        return True

    def _get_startupinfo(self):
        """Получить STARTUPINFO для скрытия консольного окна на Windows."""
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            return si
        return None

    def _check_pip(self) -> bool:
        """Проверка доступности pip (без попытки установки)."""
        try:
            result = subprocess.run(
                [self.python_exe, "-m", "pip", "--version"],
                capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=15,
                startupinfo=self._get_startupinfo()
            )
            if result.returncode == 0:
                pip_version = result.stdout.strip().split('\n')[0]
                log_info(f"Fsm_4_1_4: pip доступен: {pip_version}")
                return True
            return False
        except Exception:
            return False

    def _bootstrap_pip(self) -> bool:
        """
        Попытка установить pip через ensurepip (встроенный в Python).

        OSGeo4W Python не содержит pip по умолчанию, но содержит ensurepip.
        """
        self.emit_progress("pip не найден, попытка установки через ensurepip...")
        log_info("Fsm_4_1_4: Попытка bootstrap pip через ensurepip")

        try:
            result = subprocess.run(
                [self.python_exe, "-m", "ensurepip", "--default-pip"],
                capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=60,
                startupinfo=self._get_startupinfo()
            )

            if result.returncode == 0:
                self.emit_progress("OK pip установлен через ensurepip")
                log_info(f"Fsm_4_1_4: ensurepip успешно: {result.stdout.strip()[:200]}")
                return True
            else:
                output = (result.stderr or result.stdout or "").strip()[:300]
                log_warning(f"Fsm_4_1_4: ensurepip failed (rc={result.returncode}): {output}")
                return False

        except subprocess.TimeoutExpired:
            log_warning("Fsm_4_1_4: Таймаут ensurepip (60 сек)")
            return False
        except Exception as e:
            log_warning(f"Fsm_4_1_4: Ошибка ensurepip: {e}")
            return False

    def ensure_pip_available(self) -> bool:
        """
        Проверка и при необходимости установка pip.

        Порядок:
        1. Проверить pip --version
        2. Если нет — попробовать ensurepip (bootstrap)
        3. Проверить pip снова после bootstrap

        Returns:
            bool: True если pip доступен
        """
        if self._check_pip():
            return True

        log_warning(
            f"Fsm_4_1_4: pip недоступен в {self.python_exe}, "
            f"пробуем bootstrap через ensurepip"
        )

        if self._bootstrap_pip() and self._check_pip():
            return True

        log_error(
            f"Fsm_4_1_4: pip недоступен и ensurepip не помог. "
            f"Python: {self.python_exe}"
        )
        return False

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

        # Проверяем доступность pip (с автоматическим bootstrap через ensurepip)
        if not self.ensure_pip_available():
            msg = (
                f"pip не доступен в Python: {self.python_exe}. "
                f"Для OSGeo4W: откройте OSGeo4W Shell и выполните "
                f"'python -m ensurepip --default-pip'"
            )
            self.emit_progress(f"X {msg}")
            log_error(f"Fsm_4_1_4: {msg}")
            errors.append(msg)
            return errors

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
