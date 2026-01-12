# -*- coding: utf-8 -*-
"""
Fsm_5_1_1_DependencyChecker - Проверка Python зависимостей

Отвечает за проверку наличия и версий Python библиотек.
Читает зависимости из requirements.txt в корне плагина.
Проверяет наличие обновлений в PyPI.
"""

import sys
import os
import re
import site
import importlib
import json
import urllib.request
import urllib.error
from typing import Dict, Tuple, Optional, Any, List

from qgis.core import Qgis
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error


class DependencyChecker:
    """Проверка Python библиотек"""

    # Путь к requirements.txt относительно корня плагина
    REQUIREMENTS_FILE = "requirements.txt"

    # Описания пакетов (для UI) - НЕ версии, только метаданные
    PACKAGE_DESCRIPTIONS = {
        'ezdxf': {
            'description': 'Библиотека для работы с DXF файлами AutoCAD',
            'usage': 'Экспорт границ в формат DXF'
        },
        'xlsxwriter': {
            'description': 'Библиотека для создания Excel файлов',
            'usage': 'Экспорт координат в Excel (Приложения 2 и 3)'
        },
        'requests': {
            'description': 'Библиотека для HTTP запросов',
            'usage': 'Загрузка векторных данных ЕГРН через API НСПД'
        },
        'certifi': {
            'description': 'Пакет SSL сертификатов',
            'usage': 'Корневые сертификаты для HTTPS соединений'
        },
        'openpyxl': {
            'description': 'Библиотека для чтения и записи Excel файлов',
            'usage': 'Конвертация справочных баз данных из Excel в JSON'
        },
        'lxml': {
            'description': 'Библиотека для быстрой обработки XML',
            'usage': 'Импорт выписок ЕГРН в формате XML (F_1_1)'
        },
        'debugpy': {
            'description': 'Библиотека для удалённой отладки Python через VSCode',
            'usage': 'Отладка плагина в реальном времени с breakpoints (см. DEBUG_SETUP.md)'
        },
        'pytest': {
            'description': 'Фреймворк для тестирования Python',
            'usage': 'Автоматическое тестирование плагина (pytest tests/)'
        },
        'pytest-qgis': {
            'description': 'Плагин pytest для тестирования QGIS плагинов',
            'usage': 'Фикстуры qgis_app, qgis_iface, qgis_new_project для тестов'
        },
        'pytest-cov': {
            'description': 'Плагин pytest для отчётов покрытия кода',
            'usage': 'Coverage отчёты (--cov=Daman_QGIS --cov-report=html)'
        },
        'pytest-qt': {
            'description': 'Плагин pytest для тестирования Qt GUI',
            'usage': 'Тестирование диалогов, кнопок, ожидание Qt сигналов'
        },
        'qgis-stubs': {
            'description': 'Type stubs для PyQGIS (статическая типизация)',
            'usage': 'Type hints для pyright/pylance, автодополнение в IDE'
        }
    }

    # Библиотеки, входящие в состав QGIS (не требуют установки)
    BUILTIN_DEPENDENCIES = {
        'osgeo': {
            'min_version': None,
            'description': 'GDAL/OGR библиотека для работы с геоданными',
            'usage': 'Прямой экспорт в TAB формат с Nonearth проекцией для МСК',
            'submodules': ['ogr', 'osr', 'gdal'],
            'install_cmd': None  # Входит в состав QGIS
        }
    }

    # Кэш для EXTERNAL_DEPENDENCIES (заполняется из requirements.txt)
    _external_dependencies_cache: Optional[Dict[str, Dict]] = None

    @classmethod
    def reset_cache(cls) -> None:
        """Сброс кэша зависимостей (вызывается при reload плагина)"""
        cls._external_dependencies_cache = None

    @classmethod
    def get_requirements_path(cls) -> str:
        """Получить путь к requirements.txt"""
        # Корень плагина - 4 уровня вверх от этого файла:
        # Fsm_5_1_1_...py -> submodules -> F_5_plagin -> tools -> Daman_QGIS
        current_file = os.path.dirname(__file__)  # submodules/
        f5_plagin = os.path.dirname(current_file)  # F_5_plagin/
        tools = os.path.dirname(f5_plagin)  # tools/
        plugin_root = os.path.dirname(tools)  # Daman_QGIS/
        return os.path.join(plugin_root, cls.REQUIREMENTS_FILE)

    @classmethod
    def parse_requirements(cls) -> List[Tuple[str, Optional[str], str, bool]]:
        """
        Парсинг requirements.txt

        Returns:
            List[Tuple[str, Optional[str], str, bool]]: Список (имя_пакета, мин_версия, полная_спецификация, is_optional)
        """
        requirements_path = cls.get_requirements_path()
        requirements = []

        if not os.path.exists(requirements_path):
            log_warning(f"F_5_1: requirements.txt не найден: {requirements_path}")
            return requirements

        # Regex для парсинга: package_name>=version или package_name==version или просто package_name
        pattern = re.compile(r'^([a-zA-Z0-9_-]+)\s*([><=!~]+\s*[\d.]+)?')

        # Флаг для отслеживания секции опциональных зависимостей
        in_optional_section = False

        with open(requirements_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Пропускаем пустые строки
                if not line:
                    continue

                # Проверяем маркеры секций в комментариях
                if line.startswith('#'):
                    line_lower = line.lower()
                    # Проверяем начало секции опциональных зависимостей
                    if '[optional]' in line_lower or 'опциональн' in line_lower:
                        in_optional_section = True
                    # Проверяем начало секции обязательных зависимостей
                    elif 'обязательн' in line_lower or 'required' in line_lower:
                        in_optional_section = False
                    continue

                match = pattern.match(line)
                if match:
                    package_name = match.group(1).lower()
                    version_spec = match.group(2)

                    # Извлекаем минимальную версию из спецификации
                    min_version = None
                    if version_spec:
                        version_spec = version_spec.strip()
                        # Извлекаем числовую часть версии
                        version_match = re.search(r'[\d.]+', version_spec)
                        if version_match:
                            min_version = version_match.group()

                    requirements.append((package_name, min_version, line, in_optional_section))

        return requirements

    @classmethod
    def get_external_dependencies(cls, include_optional: bool = True) -> Dict[str, Dict]:
        """
        Внешние библиотеки из requirements.txt (lazy loading с кэшированием)

        Args:
            include_optional: Включать ли опциональные зависимости (по умолчанию True)

        Returns:
            Dict: Словарь зависимостей в формате {имя: {min_version, description, usage, install_cmd, optional}}
        """
        if cls._external_dependencies_cache is not None:
            if include_optional:
                return cls._external_dependencies_cache
            else:
                # Фильтруем только обязательные
                return {k: v for k, v in cls._external_dependencies_cache.items() if not v.get('optional', False)}

        dependencies = {}
        requirements = cls.parse_requirements()

        for package_name, min_version, full_spec, is_optional in requirements:
            # Получаем описание из PACKAGE_DESCRIPTIONS или генерируем
            desc_info = cls.PACKAGE_DESCRIPTIONS.get(package_name, {})

            dependencies[package_name] = {
                'min_version': min_version,
                'description': desc_info.get('description', f'Пакет {package_name}'),
                'usage': desc_info.get('usage', 'Используется плагином'),
                'install_cmd': f'python -m pip install {full_spec}',
                'optional': is_optional
            }

        cls._external_dependencies_cache = dependencies

        if include_optional:
            return dependencies
        else:
            return {k: v for k, v in dependencies.items() if not v.get('optional', False)}

    # Алиас для обратной совместимости (статический доступ к кэшированным данным)
    @classmethod
    def _get_external_deps(cls) -> Dict[str, Dict]:
        """Вспомогательный метод для статического доступа"""
        return cls.get_external_dependencies()

    @staticmethod
    def get_install_paths() -> Dict[str, Any]:
        """
        Определение путей для установки библиотек

        Returns:
            dict: Словарь с путями установки
        """
        from pathlib import Path
        import platform
        from qgis.core import QgsApplication

        # Изолированная папка dependencies (новый подход)
        qgis_settings_dir = QgsApplication.qgisSettingsDirPath().replace("/", os.path.sep)
        dependencies_path = os.path.join(qgis_settings_dir, "python", "dependencies")

        paths = {
            'python_exe': sys.executable,
            'python_version': platform.python_version(),
            'platform': platform.platform(),
            'dependencies_path': dependencies_path,
            'user_base': site.USER_BASE,
            'site_packages': [],
            'qgis_python': None,
            'osgeo4w_root': None
        }

        # Собираем все пути site-packages
        for p in sys.path:
            if 'site-packages' in p:
                paths['site_packages'].append(p)

        # Определяем путь QGIS Python
        for p in sys.path:
            if 'QGIS' in p and 'python' in p.lower():
                paths['qgis_python'] = p
                break

        # Определяем корень OSGeo4W
        if sys.platform == 'win32':
            exe_path = Path(sys.executable)
            for parent in exe_path.parents:
                if parent.name.lower() in ['osgeo4w', 'osgeo4w64']:
                    paths['osgeo4w_root'] = str(parent)
                    break

        # Создаём папку dependencies если не существует
        os.makedirs(dependencies_path, exist_ok=True)

        # Добавляем dependencies в sys.path если его там нет (приоритет)
        if dependencies_path not in sys.path:
            sys.path.insert(0, dependencies_path)

        return paths

    # Пакеты, которые нельзя импортировать (stub packages, meta packages)
    # Проверяются ТОЛЬКО через importlib.metadata
    NON_IMPORTABLE_PACKAGES = {
        'qgis-stubs',      # Type stubs - только .pyi файлы
        'pyqt5-stubs',     # Type stubs - только .pyi файлы
        'types-requests',  # Type stubs
    }

    # Timeout для запроса к PyPI (секунды)
    PYPI_TIMEOUT = 5

    # Кэш версий PyPI (заполняется при проверке)
    _pypi_versions_cache: Dict[str, Optional[str]] = {}

    @classmethod
    def get_pypi_version(cls, package_name: str) -> Optional[str]:
        """
        Получить последнюю версию пакета из PyPI.

        Args:
            package_name: Имя пакета

        Returns:
            str: Последняя версия или None если не удалось получить
        """
        # Проверяем кэш
        if package_name in cls._pypi_versions_cache:
            return cls._pypi_versions_cache[package_name]

        # Нормализуем имя пакета для PyPI (заменяем _ на -)
        pypi_name = package_name.replace('_', '-')
        url = f"https://pypi.org/pypi/{pypi_name}/json"

        try:
            request = urllib.request.Request(
                url,
                headers={'Accept': 'application/json', 'User-Agent': 'Daman_QGIS/1.0'}
            )
            with urllib.request.urlopen(request, timeout=cls.PYPI_TIMEOUT) as response:
                data = json.loads(response.read().decode('utf-8'))
                latest_version = data.get('info', {}).get('version')
                cls._pypi_versions_cache[package_name] = latest_version
                return latest_version
        except urllib.error.URLError as e:
            log_warning(f"F_5_1: Не удалось получить версию {package_name} из PyPI: {e.reason}")
        except urllib.error.HTTPError as e:
            log_warning(f"F_5_1: HTTP ошибка при запросе {package_name}: {e.code}")
        except json.JSONDecodeError:
            log_warning(f"F_5_1: Некорректный JSON от PyPI для {package_name}")
        except Exception as e:
            log_warning(f"F_5_1: Ошибка при запросе PyPI для {package_name}: {str(e)}")

        cls._pypi_versions_cache[package_name] = None
        return None

    @classmethod
    def check_for_update(cls, package_name: str, installed_version: Optional[str]) -> Tuple[bool, Optional[str]]:
        """
        Проверить наличие обновления для пакета.

        Args:
            package_name: Имя пакета
            installed_version: Установленная версия

        Returns:
            tuple: (есть_обновление, последняя_версия)
        """
        if not installed_version:
            return False, None

        latest_version = cls.get_pypi_version(package_name)
        if not latest_version:
            return False, None

        try:
            from packaging.version import parse as parse_version
            installed_parsed = parse_version(str(installed_version))
            latest_parsed = parse_version(str(latest_version))

            has_update = latest_parsed > installed_parsed
            return has_update, latest_version
        except Exception as e:
            log_warning(f"F_5_1: Ошибка сравнения версий {package_name}: {str(e)}")
            return False, latest_version

    @classmethod
    def reset_pypi_cache(cls) -> None:
        """Сброс кэша версий PyPI"""
        cls._pypi_versions_cache.clear()

    @classmethod
    def get_version_from_dependencies(cls, package_name: str) -> Optional[str]:
        """
        Получение версии пакета из папки dependencies (имеет приоритет над системными).

        Если есть несколько dist-info для одного пакета (после обновления pip не удалил старую),
        возвращает самую новую версию.

        Args:
            package_name: Имя пакета (например 'pytest')

        Returns:
            str или None: Версия пакета если найдена в dependencies
        """
        try:
            from Daman_QGIS.tools.F_5_plagin.submodules.Fsm_5_1_4_pip_installer import PipInstaller
            dependencies_path = PipInstaller.get_dependencies_path()

            if not os.path.exists(dependencies_path):
                return None

            # Ищем папки *.dist-info для пакета
            # Нормализуем имя пакета (pytest-qt -> pytest_qt)
            normalized_name = package_name.lower().replace('-', '_')

            # Собираем все найденные версии
            found_versions = []

            for item in os.listdir(dependencies_path):
                if item.endswith('.dist-info'):
                    # Извлекаем имя и версию из dist-info (формат: name-version.dist-info)
                    parts = item[:-10].rsplit('-', 1)  # убираем .dist-info
                    if len(parts) == 2:
                        dist_name = parts[0].lower().replace('-', '_')
                        dist_version = parts[1]
                        if dist_name == normalized_name:
                            found_versions.append(dist_version)

            if not found_versions:
                return None

            # Если несколько версий, выбираем самую новую
            if len(found_versions) == 1:
                return found_versions[0]

            # Сортируем версии и берём последнюю
            try:
                from packaging.version import parse as parse_version
                found_versions.sort(key=lambda v: parse_version(v), reverse=True)
            except ImportError:
                # Если packaging недоступен, сортируем как строки
                found_versions.sort(reverse=True)

            return found_versions[0]

        except Exception as e:
            log_warning(f"Fsm_5_1_1: Ошибка получения версии из dependencies для {package_name}: {e}")
            return None

    @classmethod
    def check_dependency(cls, module_name: str, min_version: Optional[str] = None) -> Tuple[bool, Optional[str], str]:
        """
        Проверка одной зависимости через importlib.metadata (современная альтернатива pkg_resources)

        Args:
            module_name: Имя модуля для проверки
            min_version: Минимальная требуемая версия (поддерживает >=, ==, ~= спецификации)

        Returns:
            tuple: (установлена, версия, сообщение)
        """
        # ПРИОРИТЕТ: сначала проверяем версию в папке dependencies
        # Это важно, так как pip устанавливает туда, а importlib.metadata может
        # читать из системного Python
        installed_version = cls.get_version_from_dependencies(module_name)

        if installed_version is None:
            # Если не нашли в dependencies, пробуем через importlib.metadata
            try:
                from importlib.metadata import version as get_version, PackageNotFoundError
                try:
                    installed_version = get_version(module_name)
                except PackageNotFoundError:
                    # Stub packages и meta packages нельзя импортировать - если не в metadata, значит не установлен
                    if module_name.lower() in cls.NON_IMPORTABLE_PACKAGES:
                        return False, None, "Не установлена"

                    # Для обычных пакетов пробуем импорт
                    try:
                        module = importlib.import_module(module_name)
                        # Получаем версию из атрибутов модуля
                        installed_version = None
                        if hasattr(module, '__version__'):
                            installed_version = module.__version__
                        elif hasattr(module, 'version'):
                            installed_version = module.version
                        elif hasattr(module, 'VERSION'):
                            installed_version = module.VERSION

                        if not installed_version:
                            return True, 'OK', "Установлена (версия неизвестна)"
                    except (ImportError, ModuleNotFoundError):
                        return False, None, "Не установлена"
            except ImportError:
                # Fallback для старых версий Python
                try:
                    module = importlib.import_module(module_name)
                    installed_version = getattr(module, '__version__', None) or getattr(module, 'version', None)
                except (ImportError, ModuleNotFoundError):
                    return False, None, "Не установлена"

        # Проверяем версию через packaging.version (точное сравнение)
        if min_version and installed_version:
            try:
                from packaging.version import parse as parse_version
                from packaging.specifiers import SpecifierSet, InvalidSpecifier

                # Парсим установленную версию
                try:
                    installed_parsed = parse_version(str(installed_version))
                except Exception:
                    # Если версия не парсится, считаем что OK
                    return True, installed_version, "OK (версия не стандартная)"

                # Проверяем соответствие спецификации
                # min_version может быть "1.4.2" (просто версия) или ">=1.4.2" (спецификатор)
                try:
                    # Если это просто версия без оператора, добавляем >=
                    if not any(op in str(min_version) for op in ['>', '<', '=', '~', '!']):
                        specifier = SpecifierSet(f">={min_version}")
                    else:
                        specifier = SpecifierSet(str(min_version))

                    if installed_parsed not in specifier:
                        return False, installed_version, f"Версия {installed_version} не соответствует {specifier}"
                except InvalidSpecifier:
                    # Простое сравнение если спецификатор некорректен
                    if parse_version(str(installed_version)) < parse_version(str(min_version)):
                        return False, installed_version, f"Версия {installed_version} < {min_version}"

            except ImportError:
                # packaging не установлен - пропускаем проверку версии
                log_warning(f"F_5_1: packaging не установлен, пропускаем проверку версии {module_name}")
            except Exception as e:
                log_warning(f"F_5_1: Ошибка сравнения версий {module_name}: {str(e)}")

        return True, installed_version, "OK"

    @classmethod
    def check_all_external(cls, check_updates: bool = True) -> Dict[str, Dict]:
        """
        Проверка всех внешних зависимостей (включая опциональные)

        Args:
            check_updates: Проверять наличие обновлений в PyPI (по умолчанию True)

        Returns:
            dict: Результаты проверки внешних библиотек
        """
        results = {}
        external_deps = cls.get_external_dependencies(include_optional=True)

        # Сбрасываем кэш PyPI при новой проверке
        if check_updates:
            cls.reset_pypi_cache()
            log_info("F_5_1: Проверка обновлений в PyPI...")

        for module_name, info in external_deps.items():
            installed, version, message = cls.check_dependency(
                module_name,
                info.get('min_version')
            )

            # Проверяем наличие обновлений только для установленных пакетов
            has_update = False
            latest_version = None
            if check_updates and installed and version:
                has_update, latest_version = cls.check_for_update(module_name, version)

            results[module_name] = {
                'installed': installed,
                'version': version,
                'message': message,
                'description': info['description'],
                'usage': info['usage'],
                'install_cmd': info['install_cmd'],
                'optional': info.get('optional', False),
                'has_update': has_update,
                'latest_version': latest_version
            }

        return results

    @staticmethod
    def check_all_builtin() -> Dict[str, Dict]:
        """
        Проверка всех встроенных зависимостей QGIS

        Returns:
            dict: Результаты проверки встроенных библиотек
        """
        results = {}

        for module_name, info in DependencyChecker.BUILTIN_DEPENDENCIES.items():
            installed, version, message = DependencyChecker.check_dependency(
                module_name,
                info.get('min_version')
            )

            # Проверка субмодулей
            submodules_ok = True
            submodules_status = []
            if installed and 'submodules' in info:
                for submodule in info['submodules']:
                    try:
                        full_name = f"{module_name}.{submodule}"
                        importlib.import_module(full_name)
                        submodules_status.append(submodule)
                    except (ImportError, ModuleNotFoundError):
                        submodules_ok = False
                        submodules_status.append(f"X {submodule}")

            results[module_name] = {
                'installed': installed and submodules_ok,
                'version': version,
                'message': message if not installed else ', '.join(submodules_status),
                'description': info['description'],
                'usage': info['usage'],
                'install_cmd': info['install_cmd']
            }

        return results

    @classmethod
    def quick_check(cls) -> bool:
        """
        Быстрая проверка зависимостей при запуске плагина.
        Проверяет только ОБЯЗАТЕЛЬНЫЕ зависимости (не опциональные).
        Записывает краткий результат в лог.

        Returns:
            bool: True если все обязательные зависимости установлены
        """
        missing = []
        installed = []
        installed_with_versions = []
        # Получаем только обязательные зависимости (include_optional=False)
        required_deps = cls.get_external_dependencies(include_optional=False)

        for module_name in required_deps.keys():
            try:
                module = importlib.import_module(module_name)
                # Пытаемся получить версию разными способами
                version = None
                if hasattr(module, '__version__'):
                    version = module.__version__
                elif hasattr(module, 'version'):
                    version = module.version
                elif hasattr(module, 'VERSION'):
                    version = module.VERSION

                # Если не нашли, пытаемся через importlib.metadata (Python 3.8+)
                if not version:
                    try:
                        from importlib.metadata import version as get_version
                        version = get_version(module_name)
                    except Exception:
                        version = 'OK'  # Просто отмечаем что установлена

                installed.append(module_name)
                installed_with_versions.append(f"{module_name} ({version})")
            except (ImportError, ModuleNotFoundError):
                missing.append(module_name)

        if not missing:
            log_info(f"F_5_1: Все обязательные зависимости установлены ({len(installed)} библиотек)")
            return True
        else:
            log_warning(f"F_5_1: Не установлены обязательные зависимости: {', '.join(missing)}")
            if installed:
                log_info(f"F_5_1: Установлены: {', '.join(installed_with_versions)}")
            return False
