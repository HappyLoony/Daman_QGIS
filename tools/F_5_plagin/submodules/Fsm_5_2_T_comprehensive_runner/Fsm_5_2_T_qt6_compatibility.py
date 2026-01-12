# -*- coding: utf-8 -*-
"""
Fsm_5_2_T_qt6_compatibility - Тест совместимости с Qt6/QGIS 4.0

Проверяет готовность плагина к миграции на Qt6 (QGIS 4.0, февраль 2026).

Проверки:
1. Использование qgis.PyQt вместо прямых импортов PyQt5/PyQt6
2. Полностью квалифицированные enum (Qt.ItemDataRole.UserRole вместо Qt.UserRole)
3. Перемещённые классы (QAction -> QtGui)
4. Deprecated API: exec_(), print_(), qApp
5. Удалённые модули Qt (QtScript, QtWebKit и др.)
6. metadata.txt: supportsQt6, qgisMaximumVersion

Основано на:
- https://github.com/qgis/QGIS/wiki/Plugin-migration-to-be-compatible-with-Qt5-and-Qt6
- https://blog.qgis.org/2025/04/17/qgis-is-moving-to-qt6-and-launching-qgis-4-0/
- https://www.riverbankcomputing.com/static/Docs/PyQt6/pyqt5_differences.html
"""

import os
import re
from typing import Any, Dict, List, Tuple, Set
from pathlib import Path


class TestQt6Compatibility:
    """Тесты совместимости с Qt6"""

    # Паттерны импортов, которые нужно заменить на qgis.PyQt
    DEPRECATED_IMPORTS = [
        (r'from PyQt5\.', 'from qgis.PyQt.'),
        (r'from PyQt6\.', 'from qgis.PyQt.'),
        (r'import PyQt5', 'from qgis import PyQt'),
        (r'import PyQt6', 'from qgis import PyQt'),
    ]

    # Enum паттерны Qt5 -> Qt6 (неполные квалификации)
    # Формат: (старый паттерн, новый паттерн, описание)
    ENUM_PATTERNS: List[Tuple[str, str, str]] = [
        # Qt namespace enums
        (r'Qt\.UserRole(?!\w)', 'Qt.ItemDataRole.UserRole', 'Qt.UserRole'),
        (r'Qt\.DisplayRole(?!\w)', 'Qt.ItemDataRole.DisplayRole', 'Qt.DisplayRole'),
        (r'Qt\.EditRole(?!\w)', 'Qt.ItemDataRole.EditRole', 'Qt.EditRole'),
        (r'Qt\.CheckStateRole(?!\w)', 'Qt.ItemDataRole.CheckStateRole', 'Qt.CheckStateRole'),
        (r'Qt\.WaitCursor(?!\w)', 'Qt.CursorShape.WaitCursor', 'Qt.WaitCursor'),
        (r'Qt\.ArrowCursor(?!\w)', 'Qt.CursorShape.ArrowCursor', 'Qt.ArrowCursor'),
        (r'Qt\.CrossCursor(?!\w)', 'Qt.CursorShape.CrossCursor', 'Qt.CrossCursor'),
        (r'Qt\.Horizontal(?!\w)', 'Qt.Orientation.Horizontal', 'Qt.Horizontal'),
        (r'Qt\.Vertical(?!\w)', 'Qt.Orientation.Vertical', 'Qt.Vertical'),
        (r'Qt\.AlignLeft(?!\w)', 'Qt.AlignmentFlag.AlignLeft', 'Qt.AlignLeft'),
        (r'Qt\.AlignRight(?!\w)', 'Qt.AlignmentFlag.AlignRight', 'Qt.AlignRight'),
        (r'Qt\.AlignCenter(?!\w)', 'Qt.AlignmentFlag.AlignCenter', 'Qt.AlignCenter'),
        (r'Qt\.AlignVCenter(?!\w)', 'Qt.AlignmentFlag.AlignVCenter', 'Qt.AlignVCenter'),
        (r'Qt\.AlignHCenter(?!\w)', 'Qt.AlignmentFlag.AlignHCenter', 'Qt.AlignHCenter'),
        (r'Qt\.white(?!\w)', 'Qt.GlobalColor.white', 'Qt.white'),
        (r'Qt\.black(?!\w)', 'Qt.GlobalColor.black', 'Qt.black'),
        (r'Qt\.red(?!\w)', 'Qt.GlobalColor.red', 'Qt.red'),
        (r'Qt\.blue(?!\w)', 'Qt.GlobalColor.blue', 'Qt.blue'),
        (r'Qt\.green(?!\w)', 'Qt.GlobalColor.green', 'Qt.green'),
        (r'Qt\.Checked(?!\w)', 'Qt.CheckState.Checked', 'Qt.Checked'),
        (r'Qt\.Unchecked(?!\w)', 'Qt.CheckState.Unchecked', 'Qt.Unchecked'),
        (r'Qt\.PartiallyChecked(?!\w)', 'Qt.CheckState.PartiallyChecked', 'Qt.PartiallyChecked'),
        (r'Qt\.KeepAspectRatio(?!\w)', 'Qt.AspectRatioMode.KeepAspectRatio', 'Qt.KeepAspectRatio'),
        (r'Qt\.IgnoreAspectRatio(?!\w)', 'Qt.AspectRatioMode.IgnoreAspectRatio', 'Qt.IgnoreAspectRatio'),

        # QMessageBox enums
        (r'QMessageBox\.Ok(?!\w)', 'QMessageBox.StandardButton.Ok', 'QMessageBox.Ok'),
        (r'QMessageBox\.Cancel(?!\w)', 'QMessageBox.StandardButton.Cancel', 'QMessageBox.Cancel'),
        (r'QMessageBox\.Yes(?!\w)', 'QMessageBox.StandardButton.Yes', 'QMessageBox.Yes'),
        (r'QMessageBox\.No(?!\w)', 'QMessageBox.StandardButton.No', 'QMessageBox.No'),
        (r'QMessageBox\.Warning(?!\w)', 'QMessageBox.Icon.Warning', 'QMessageBox.Warning'),
        (r'QMessageBox\.Critical(?!\w)', 'QMessageBox.Icon.Critical', 'QMessageBox.Critical'),
        (r'QMessageBox\.Information(?!\w)', 'QMessageBox.Icon.Information', 'QMessageBox.Information'),
        (r'QMessageBox\.Question(?!\w)', 'QMessageBox.Icon.Question', 'QMessageBox.Question'),

        # QFileDialog enums
        (r'QFileDialog\.AcceptOpen(?!\w)', 'QFileDialog.AcceptMode.AcceptOpen', 'QFileDialog.AcceptOpen'),
        (r'QFileDialog\.AcceptSave(?!\w)', 'QFileDialog.AcceptMode.AcceptSave', 'QFileDialog.AcceptSave'),
        (r'QFileDialog\.ExistingFile(?!\w)', 'QFileDialog.FileMode.ExistingFile', 'QFileDialog.ExistingFile'),
        (r'QFileDialog\.Directory(?!\w)', 'QFileDialog.FileMode.Directory', 'QFileDialog.Directory'),

        # QSizePolicy enums
        (r'QSizePolicy\.Expanding(?!\w)', 'QSizePolicy.Policy.Expanding', 'QSizePolicy.Expanding'),
        (r'QSizePolicy\.Fixed(?!\w)', 'QSizePolicy.Policy.Fixed', 'QSizePolicy.Fixed'),
        (r'QSizePolicy\.Minimum(?!\w)', 'QSizePolicy.Policy.Minimum', 'QSizePolicy.Minimum'),
        (r'QSizePolicy\.Maximum(?!\w)', 'QSizePolicy.Policy.Maximum', 'QSizePolicy.Policy.Maximum'),

        # QgsMapLayer enums
        (r'QgsMapLayer\.VectorLayer(?!\w)', 'QgsMapLayer.LayerType.VectorLayer', 'QgsMapLayer.VectorLayer'),
        (r'QgsMapLayer\.RasterLayer(?!\w)', 'QgsMapLayer.LayerType.RasterLayer', 'QgsMapLayer.RasterLayer'),

        # QVariant (QMetaType in Qt6)
        (r'QVariant\.String(?!\w)', 'QMetaType.Type.QString', 'QVariant.String -> QMetaType'),
        (r'QVariant\.Int(?!\w)', 'QMetaType.Type.Int', 'QVariant.Int -> QMetaType'),
        (r'QVariant\.Double(?!\w)', 'QMetaType.Type.Double', 'QVariant.Double -> QMetaType'),
    ]

    # Классы, которые переместились между модулями в Qt6
    RELOCATED_CLASSES = {
        'QAction': ('QtWidgets', 'QtGui'),
        'QShortcut': ('QtWidgets', 'QtGui'),
        'QActionGroup': ('QtWidgets', 'QtGui'),
    }

    # Deprecated методы в PyQt6 (удалены)
    # exec_() и print_() были workaround для Python 2, в Python 3 не нужны
    DEPRECATED_METHODS = [
        (r'\.exec_\(\)', '.exec()', 'exec_() удалён в PyQt6'),
        (r'\.print_\(\)', '.print()', 'print_() удалён в PyQt6'),
    ]

    # Удалённые глобальные объекты
    REMOVED_GLOBALS = [
        (r'\bqApp\b', 'QApplication.instance()', 'qApp удалён в PyQt6'),
        (r'PYQT_CONFIGURATION', 'Удалён', 'PYQT_CONFIGURATION удалён'),
    ]

    # Удалённые/перемещённые модули Qt в Qt6
    REMOVED_MODULES = [
        'QtScript',           # Полностью удалён
        'QtScriptTools',      # Полностью удалён
        'QtWebKit',           # Заменён на QtWebEngine
        'QtWebKitWidgets',    # Заменён на QtWebEngineWidgets
        'QtMultimedia',       # Не в qgis.PyQt (отдельный пакет)
        'QtMultimediaWidgets',
    ]

    def __init__(self, iface: Any, logger: Any) -> None:
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.plugin_root = self._get_plugin_root()
        self.issues: List[Dict[str, Any]] = []

    def _get_plugin_root(self) -> str:
        """Получить корневую папку плагина"""
        current = os.path.dirname(__file__)
        for _ in range(4):
            current = os.path.dirname(current)
        return current

    def run_all_tests(self) -> None:
        """Запуск всех тестов совместимости Qt6"""
        self.logger.section("ТЕСТ СОВМЕСТИМОСТИ С Qt6/QGIS 4.0")

        try:
            self.test_01_check_metadata()
            self.test_02_check_imports()
            self.test_03_check_enum_patterns()
            self.test_04_check_relocated_classes()
            self.test_05_check_qvariant_usage()
            self.test_06_check_deprecated_methods()
            self.test_07_check_removed_globals()
            self.test_08_check_removed_modules()
            self.test_09_summary()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов Qt6: {str(e)}")

        self.logger.summary()

    def _get_python_files(self) -> List[Path]:
        """Получить все Python файлы плагина"""
        plugin_path = Path(self.plugin_root)
        python_files = []

        exclude_dirs = {'__pycache__', '.git', '.vscode', 'external_modules', 'ВРЕМ', '_delete'}

        for py_file in plugin_path.rglob('*.py'):
            # Пропускаем исключённые директории
            if any(excluded in py_file.parts for excluded in exclude_dirs):
                continue
            python_files.append(py_file)

        return python_files

    def test_01_check_metadata(self) -> None:
        """ТЕСТ 1: Проверка metadata.txt"""
        self.logger.section("1. Проверка metadata.txt")

        metadata_path = os.path.join(self.plugin_root, 'metadata.txt')

        if not os.path.exists(metadata_path):
            self.logger.warning("metadata.txt не найден")
            return

        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Проверяем supportsQt6
            if 'supportsQt6=True' in content:
                self.logger.success("supportsQt6=True установлен")
            elif 'supportsQt6' in content:
                self.logger.warning("supportsQt6 найден, но не True")
            else:
                self.logger.warning("supportsQt6 не указан (добавьте supportsQt6=True)")
                self.issues.append({
                    'file': 'metadata.txt',
                    'issue': 'Отсутствует supportsQt6=True',
                    'severity': 'warning'
                })

            # Проверяем qgisMaximumVersion
            max_version_match = re.search(r'qgisMaximumVersion=(\d+\.\d+)', content)
            if max_version_match:
                max_version = max_version_match.group(1)
                if float(max_version) >= 4.99:
                    self.logger.success(f"qgisMaximumVersion={max_version} (готов к QGIS 4)")
                else:
                    self.logger.warning(f"qgisMaximumVersion={max_version} (обновите до 4.99 для QGIS 4)")
            else:
                self.logger.info("qgisMaximumVersion не указан")

        except Exception as e:
            self.logger.error(f"Ошибка чтения metadata.txt: {e}")

    def test_02_check_imports(self) -> None:
        """ТЕСТ 2: Проверка импортов PyQt"""
        self.logger.section("2. Проверка импортов PyQt")

        python_files = self._get_python_files()
        direct_imports: List[Tuple[str, int, str]] = []

        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()

                for line_num, line in enumerate(lines, 1):
                    # Ищем прямые импорты PyQt5/PyQt6
                    if re.search(r'from PyQt[56]\.', line) or re.search(r'import PyQt[56]', line):
                        # Исключаем комментарии
                        if not line.strip().startswith('#'):
                            rel_path = py_file.relative_to(self.plugin_root)
                            direct_imports.append((str(rel_path), line_num, line.strip()))

            except Exception as e:
                self.logger.warning(f"Ошибка чтения {py_file}: {e}")

        if direct_imports:
            self.logger.warning(f"Найдено {len(direct_imports)} прямых импортов PyQt5/PyQt6")
            # Показываем первые 5
            for file_path, line_num, line in direct_imports[:5]:
                self.logger.info(f"  {file_path}:{line_num}")
                self.issues.append({
                    'file': file_path,
                    'line': line_num,
                    'issue': f'Прямой импорт PyQt: {line[:50]}',
                    'fix': 'Заменить на from qgis.PyQt...',
                    'severity': 'warning'
                })
            if len(direct_imports) > 5:
                self.logger.info(f"  ... и ещё {len(direct_imports) - 5}")
        else:
            self.logger.success("Все импорты используют qgis.PyQt")

    def test_03_check_enum_patterns(self) -> None:
        """ТЕСТ 3: Проверка enum паттернов"""
        self.logger.section("3. Проверка enum паттернов (Qt5 -> Qt6)")

        python_files = self._get_python_files()
        enum_issues: Dict[str, List[Tuple[str, int, str]]] = {}

        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    lines = content.split('\n')

                for pattern, replacement, description in self.ENUM_PATTERNS:
                    for line_num, line in enumerate(lines, 1):
                        # Пропускаем комментарии и строки
                        stripped = line.strip()
                        if stripped.startswith('#') or stripped.startswith('"') or stripped.startswith("'"):
                            continue

                        if re.search(pattern, line):
                            rel_path = str(py_file.relative_to(self.plugin_root))
                            if description not in enum_issues:
                                enum_issues[description] = []
                            enum_issues[description].append((rel_path, line_num, line.strip()[:60]))

            except Exception as e:
                pass  # Игнорируем ошибки чтения

        if enum_issues:
            total_issues = sum(len(v) for v in enum_issues.values())
            self.logger.warning(f"Найдено {total_issues} устаревших enum паттернов")

            # Группируем по типу
            for enum_type, occurrences in list(enum_issues.items())[:5]:
                self.logger.info(f"  {enum_type}: {len(occurrences)} использований")
                self.issues.append({
                    'issue': f'Устаревший enum: {enum_type}',
                    'count': len(occurrences),
                    'severity': 'warning'
                })

            if len(enum_issues) > 5:
                self.logger.info(f"  ... и ещё {len(enum_issues) - 5} типов")
        else:
            self.logger.success("Все enum используют Qt6-совместимый синтаксис")

    def test_04_check_relocated_classes(self) -> None:
        """ТЕСТ 4: Проверка перемещённых классов"""
        self.logger.section("4. Проверка перемещённых классов")

        python_files = self._get_python_files()
        relocation_issues: List[Tuple[str, int, str, str]] = []

        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()

                for line_num, line in enumerate(lines, 1):
                    for class_name, (old_module, new_module) in self.RELOCATED_CLASSES.items():
                        # Ищем импорт из старого модуля
                        pattern = rf'from\s+(?:qgis\.)?PyQt\.{old_module}\s+import\s+.*\b{class_name}\b'
                        if re.search(pattern, line):
                            rel_path = str(py_file.relative_to(self.plugin_root))
                            relocation_issues.append((rel_path, line_num, class_name, f'{old_module} -> {new_module}'))

            except Exception as e:
                pass

        if relocation_issues:
            self.logger.warning(f"Найдено {len(relocation_issues)} импортов перемещённых классов")
            for file_path, line_num, class_name, move in relocation_issues[:5]:
                self.logger.info(f"  {file_path}:{line_num} - {class_name} ({move})")
                self.issues.append({
                    'file': file_path,
                    'line': line_num,
                    'issue': f'{class_name} перемещён: {move}',
                    'severity': 'info'
                })
        else:
            self.logger.success("Перемещённые классы корректно импортированы")

    def test_05_check_qvariant_usage(self) -> None:
        """ТЕСТ 5: Проверка использования QVariant (deprecated в Qt6)"""
        self.logger.section("5. Проверка QVariant (deprecated)")

        python_files = self._get_python_files()
        qvariant_issues: List[Tuple[str, int]] = []

        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()

                for line_num, line in enumerate(lines, 1):
                    # Ищем использование QVariant типов (кроме QMetaType)
                    if re.search(r'QVariant\.(String|Int|Double|Bool|Date|DateTime|Invalid)', line):
                        if not line.strip().startswith('#'):
                            rel_path = str(py_file.relative_to(self.plugin_root))
                            qvariant_issues.append((rel_path, line_num))

            except Exception as e:
                pass

        if qvariant_issues:
            self.logger.warning(f"Найдено {len(qvariant_issues)} использований QVariant типов")
            self.logger.info("  Рекомендуется использовать QMetaType.Type.* вместо QVariant.*")
            for file_path, line_num in qvariant_issues[:3]:
                self.logger.info(f"  {file_path}:{line_num}")
        else:
            self.logger.success("QVariant типы не используются (или уже QMetaType)")

    def test_06_check_deprecated_methods(self) -> None:
        """ТЕСТ 6: Проверка deprecated методов (exec_(), print_())"""
        self.logger.section("6. Проверка deprecated методов")

        python_files = self._get_python_files()
        deprecated_issues: List[Tuple[str, int, str, str]] = []

        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()

                for line_num, line in enumerate(lines, 1):
                    if line.strip().startswith('#'):
                        continue

                    for pattern, replacement, description in self.DEPRECATED_METHODS:
                        if re.search(pattern, line):
                            rel_path = str(py_file.relative_to(self.plugin_root))
                            deprecated_issues.append((rel_path, line_num, description, replacement))

            except Exception:
                pass

        if deprecated_issues:
            self.logger.warning(f"Найдено {len(deprecated_issues)} использований deprecated методов")
            for file_path, line_num, desc, fix in deprecated_issues[:5]:
                self.logger.info(f"  {file_path}:{line_num} - {desc}")
                self.issues.append({
                    'file': file_path,
                    'line': line_num,
                    'issue': desc,
                    'fix': fix,
                    'severity': 'warning'
                })
            if len(deprecated_issues) > 5:
                self.logger.info(f"  ... и ещё {len(deprecated_issues) - 5}")
        else:
            self.logger.success("Deprecated методы (exec_(), print_()) не используются")

    def test_07_check_removed_globals(self) -> None:
        """ТЕСТ 7: Проверка удалённых глобальных объектов (qApp)"""
        self.logger.section("7. Проверка удалённых глобальных объектов")

        python_files = self._get_python_files()
        global_issues: List[Tuple[str, int, str, str]] = []

        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()

                for line_num, line in enumerate(lines, 1):
                    if line.strip().startswith('#'):
                        continue

                    for pattern, replacement, description in self.REMOVED_GLOBALS:
                        if re.search(pattern, line):
                            rel_path = str(py_file.relative_to(self.plugin_root))
                            global_issues.append((rel_path, line_num, description, replacement))

            except Exception:
                pass

        if global_issues:
            self.logger.warning(f"Найдено {len(global_issues)} использований удалённых глобальных объектов")
            for file_path, line_num, desc, fix in global_issues[:5]:
                self.logger.info(f"  {file_path}:{line_num} - {desc}")
                self.issues.append({
                    'file': file_path,
                    'line': line_num,
                    'issue': desc,
                    'fix': fix,
                    'severity': 'warning'
                })
            if len(global_issues) > 5:
                self.logger.info(f"  ... и ещё {len(global_issues) - 5}")
        else:
            self.logger.success("Удалённые глобальные объекты (qApp) не используются")

    def test_08_check_removed_modules(self) -> None:
        """ТЕСТ 8: Проверка удалённых модулей Qt"""
        self.logger.section("8. Проверка удалённых модулей Qt")

        python_files = self._get_python_files()
        module_issues: List[Tuple[str, int, str]] = []

        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()

                for line_num, line in enumerate(lines, 1):
                    if line.strip().startswith('#'):
                        continue

                    for module in self.REMOVED_MODULES:
                        # Ищем импорт удалённого модуля
                        if re.search(rf'from\s+.*{module}\s+import', line) or \
                           re.search(rf'import\s+.*{module}', line):
                            rel_path = str(py_file.relative_to(self.plugin_root))
                            module_issues.append((rel_path, line_num, module))

            except Exception:
                pass

        if module_issues:
            self.logger.warning(f"Найдено {len(module_issues)} импортов удалённых модулей Qt")
            for file_path, line_num, module in module_issues[:5]:
                self.logger.info(f"  {file_path}:{line_num} - {module}")
                self.issues.append({
                    'file': file_path,
                    'line': line_num,
                    'issue': f'Удалённый модуль: {module}',
                    'severity': 'error'
                })
            if len(module_issues) > 5:
                self.logger.info(f"  ... и ещё {len(module_issues) - 5}")
        else:
            self.logger.success("Удалённые модули Qt не используются")

    def test_09_summary(self) -> None:
        """ТЕСТ 9: Итоговая сводка"""
        self.logger.section("9. Итоговая сводка Qt6 совместимости")

        if not self.issues:
            self.logger.success("Плагин готов к Qt6/QGIS 4.0!")
            self.logger.info("Рекомендации:")
            self.logger.info("  - Протестировать на QGIS Qt6 сборке")
            self.logger.info("  - Добавить supportsQt6=True в metadata.txt")
        else:
            errors = [i for i in self.issues if i.get('severity') == 'error']
            warnings = [i for i in self.issues if i.get('severity') == 'warning']
            infos = [i for i in self.issues if i.get('severity') == 'info']

            if errors:
                self.logger.error(f"Критических проблем: {len(errors)}")
            self.logger.warning(f"Найдено проблем: {len(warnings)} предупреждений, {len(infos)} информационных")
            self.logger.info("Рекомендуемые действия:")
            self.logger.info("  1. Запустить скрипт миграции: pyqt5_to_pyqt6.py")
            self.logger.info("  2. Заменить exec_() на exec()")
            self.logger.info("  3. Заменить qApp на QApplication.instance()")
            self.logger.info("  4. Заменить прямые импорты PyQt5 на qgis.PyQt")
            self.logger.info("  5. Обновить enum на полные квалификации")
            self.logger.info("  6. Протестировать на QGIS Qt6 сборке")
            self.logger.info("  Docker: registry.gitlab.com/oslandia/qgis/pyqgis-4-checker")
