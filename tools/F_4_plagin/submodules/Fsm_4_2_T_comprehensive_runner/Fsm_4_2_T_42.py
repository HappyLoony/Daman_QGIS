# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_42 - Тестирование M_42 AutoUpdateManager

Тестирует:
- _validate_zip() с валидным ZIP
- _validate_zip() path traversal (../../etc/passwd)
- _validate_zip() абсолютные пути
- _validate_zip() без metadata.txt
- _validate_zip() corrupted ZIP
- _is_newer() сравнение версий
"""

import io
import zipfile
from typing import Any


class TestAutoUpdateManager:
    """Тесты M_42 AutoUpdateManager"""

    def __init__(self, iface: Any, logger: Any) -> None:
        self.iface = iface
        self.logger = logger

    def run_all_tests(self) -> None:
        """Entry point for comprehensive runner"""
        self.logger.section("ТЕСТ M_42: AutoUpdateManager")

        try:
            # 1. Импорт и существование класса
            self.test_01_import()

            # 2. _validate_zip
            self.test_02_valid_zip()
            self.test_03_path_traversal()
            self.test_04_absolute_path()
            self.test_05_no_metadata()
            self.test_06_corrupt_zip()
            self.test_07_empty_zip()

            # 3. _is_newer
            self.test_10_newer_version()
            self.test_11_older_version()
            self.test_12_same_version()
            self.test_13_malformed_version()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов M_42: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    # =========================================================================
    # Helpers
    # =========================================================================

    def _get_manager(self) -> Any:
        """Создать экземпляр AutoUpdateManager."""
        from Daman_QGIS.managers.infrastructure.M_42_auto_update_manager import (
            AutoUpdateManager,
        )
        return AutoUpdateManager()

    def _make_zip_bytes(self, entries: dict) -> bytes:
        """Создать ZIP в памяти из словаря {path: content}.

        Args:
            entries: {"Daman_QGIS/metadata.txt": "version=1.0"}

        Returns:
            bytes ZIP-архива
        """
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for path, content in entries.items():
                zf.writestr(path, content)
        return buf.getvalue()

    # =========================================================================
    # 1. Импорт
    # =========================================================================

    def test_01_import(self) -> None:
        """TEST 1: Импорт модуля и существование класса"""
        self.logger.section("1. Импорт M_42")

        try:
            from Daman_QGIS.managers.infrastructure.M_42_auto_update_manager import (
                AutoUpdateManager,
            )

            self.logger.check(
                AutoUpdateManager is not None,
                "AutoUpdateManager импортирован",
                "AutoUpdateManager не найден"
            )

            manager = AutoUpdateManager()
            self.logger.check(
                hasattr(manager, '_validate_zip'),
                "_validate_zip() существует",
                "_validate_zip() не найден"
            )
            self.logger.check(
                hasattr(manager, '_is_newer'),
                "_is_newer() существует",
                "_is_newer() не найден"
            )
            self.logger.check(
                hasattr(manager, 'check_and_update'),
                "check_and_update() существует",
                "check_and_update() не найден"
            )
            self.logger.check(
                hasattr(manager, 'force_reinstall'),
                "force_reinstall() существует",
                "force_reinstall() не найден"
            )

        except Exception as e:
            self.logger.error(f"Импорт M_42: {e}")

    # =========================================================================
    # 2. _validate_zip
    # =========================================================================

    def test_02_valid_zip(self) -> None:
        """TEST 2: _validate_zip -- валидный ZIP с metadata.txt"""
        self.logger.section("2. validate_zip: валидный ZIP")

        try:
            from Daman_QGIS.constants import PLUGIN_NAME

            manager = self._get_manager()

            zip_data = self._make_zip_bytes({
                f"{PLUGIN_NAME}/metadata.txt": "version=1.0.0\nname=Daman_QGIS",
                f"{PLUGIN_NAME}/__init__.py": "# init",
                f"{PLUGIN_NAME}/utils.py": "# utils",
            })

            result = manager._validate_zip(zip_data)
            self.logger.check(
                result is True,
                "Валидный ZIP: _validate_zip() = True",
                f"Валидный ZIP: _validate_zip() вернул {result}, ожидали True"
            )

        except Exception as e:
            self.logger.error(f"validate_zip валидный: {e}")

    def test_03_path_traversal(self) -> None:
        """TEST 3: _validate_zip -- path traversal (../../etc/passwd)"""
        self.logger.section("3. validate_zip: path traversal")

        try:
            from Daman_QGIS.constants import PLUGIN_NAME

            manager = self._get_manager()

            # ZIP с path traversal записью
            zip_data = self._make_zip_bytes({
                f"{PLUGIN_NAME}/metadata.txt": "version=1.0.0",
                "../../etc/passwd": "root:x:0:0",
            })

            result = manager._validate_zip(zip_data)
            self.logger.check(
                result is False,
                "Path traversal (..): _validate_zip() = False",
                f"Path traversal (..): _validate_zip() вернул {result}, УЯЗВИМОСТЬ!"
            )

            # Вариант с .. внутри пути
            zip_data_2 = self._make_zip_bytes({
                f"{PLUGIN_NAME}/metadata.txt": "version=1.0.0",
                f"{PLUGIN_NAME}/subdir/../../../etc/shadow": "data",
            })

            result_2 = manager._validate_zip(zip_data_2)
            self.logger.check(
                result_2 is False,
                "Path traversal (вложенный ..): _validate_zip() = False",
                f"Path traversal (вложенный ..): _validate_zip() вернул {result_2}, УЯЗВИМОСТЬ!"
            )

        except Exception as e:
            self.logger.error(f"validate_zip path traversal: {e}")

    def test_04_absolute_path(self) -> None:
        """TEST 4: _validate_zip -- абсолютные пути"""
        self.logger.section("4. validate_zip: абсолютные пути")

        try:
            from Daman_QGIS.constants import PLUGIN_NAME

            manager = self._get_manager()

            zip_data = self._make_zip_bytes({
                f"{PLUGIN_NAME}/metadata.txt": "version=1.0.0",
                "/etc/passwd": "root:x:0:0",
            })

            result = manager._validate_zip(zip_data)
            self.logger.check(
                result is False,
                "Абсолютный путь (/etc/passwd): _validate_zip() = False",
                f"Абсолютный путь: _validate_zip() вернул {result}, УЯЗВИМОСТЬ!"
            )

        except Exception as e:
            self.logger.error(f"validate_zip абсолютный путь: {e}")

    def test_05_no_metadata(self) -> None:
        """TEST 5: _validate_zip -- ZIP без metadata.txt"""
        self.logger.section("5. validate_zip: без metadata.txt")

        try:
            from Daman_QGIS.constants import PLUGIN_NAME

            manager = self._get_manager()

            # ZIP без metadata.txt
            zip_data = self._make_zip_bytes({
                f"{PLUGIN_NAME}/__init__.py": "# init",
                f"{PLUGIN_NAME}/utils.py": "# utils",
            })

            result = manager._validate_zip(zip_data)
            self.logger.check(
                result is False,
                "Без metadata.txt: _validate_zip() = False",
                f"Без metadata.txt: _validate_zip() вернул {result}, ожидали False"
            )

            # metadata.txt в неправильной папке
            zip_data_wrong = self._make_zip_bytes({
                "WrongPlugin/metadata.txt": "version=1.0.0",
            })

            result_wrong = manager._validate_zip(zip_data_wrong)
            self.logger.check(
                result_wrong is False,
                "metadata.txt в чужой папке: _validate_zip() = False",
                f"metadata.txt в чужой папке: вернул {result_wrong}, ожидали False"
            )

        except Exception as e:
            self.logger.error(f"validate_zip без metadata: {e}")

    def test_06_corrupt_zip(self) -> None:
        """TEST 6: _validate_zip -- повреждённый ZIP (мусорные байты)"""
        self.logger.section("6. validate_zip: повреждённый ZIP")

        try:
            manager = self._get_manager()

            corrupt_data = b"This is not a ZIP file at all, just garbage bytes"

            result = manager._validate_zip(corrupt_data)
            self.logger.check(
                result is False,
                "Мусорные байты: _validate_zip() = False",
                f"Мусорные байты: _validate_zip() вернул {result}, ожидали False"
            )

            # Частично повреждённый (начало ZIP, обрезанный)
            from Daman_QGIS.constants import PLUGIN_NAME

            valid_zip = self._make_zip_bytes({
                f"{PLUGIN_NAME}/metadata.txt": "version=1.0.0",
            })
            truncated = valid_zip[:len(valid_zip) // 2]

            result_trunc = manager._validate_zip(truncated)
            self.logger.check(
                result_trunc is False,
                "Обрезанный ZIP: _validate_zip() = False",
                f"Обрезанный ZIP: _validate_zip() вернул {result_trunc}, ожидали False"
            )

        except Exception as e:
            self.logger.error(f"validate_zip повреждённый: {e}")

    def test_07_empty_zip(self) -> None:
        """TEST 7: _validate_zip -- пустой ZIP (без файлов)"""
        self.logger.section("7. validate_zip: пустой ZIP")

        try:
            manager = self._get_manager()

            # Валидный ZIP-архив, но без файлов внутри
            empty_zip = self._make_zip_bytes({})

            result = manager._validate_zip(empty_zip)
            self.logger.check(
                result is False,
                "Пустой ZIP: _validate_zip() = False",
                f"Пустой ZIP: _validate_zip() вернул {result}, ожидали False"
            )

            # Пустые байты
            result_empty = manager._validate_zip(b"")
            self.logger.check(
                result_empty is False,
                "Пустые байты: _validate_zip() = False",
                f"Пустые байты: _validate_zip() вернул {result_empty}, ожидали False"
            )

        except Exception as e:
            self.logger.error(f"validate_zip пустой: {e}")

    # =========================================================================
    # 3. _is_newer
    # =========================================================================

    def test_10_newer_version(self) -> None:
        """TEST 10: _is_newer -- remote новее local"""
        self.logger.section("10. is_newer: remote новее")

        try:
            manager = self._get_manager()

            result = manager._is_newer("1.2.0", "1.1.0")
            self.logger.check(
                result is True,
                "1.2.0 > 1.1.0: _is_newer() = True",
                f"1.2.0 > 1.1.0: _is_newer() вернул {result}"
            )

            result_2 = manager._is_newer("0.9.500", "0.9.499")
            self.logger.check(
                result_2 is True,
                "0.9.500 > 0.9.499: _is_newer() = True",
                f"0.9.500 > 0.9.499: _is_newer() вернул {result_2}"
            )

            result_3 = manager._is_newer("2.0.0", "1.99.99")
            self.logger.check(
                result_3 is True,
                "2.0.0 > 1.99.99: _is_newer() = True",
                f"2.0.0 > 1.99.99: _is_newer() вернул {result_3}"
            )

        except Exception as e:
            self.logger.error(f"is_newer (remote новее): {e}")

    def test_11_older_version(self) -> None:
        """TEST 11: _is_newer -- remote старее local"""
        self.logger.section("11. is_newer: remote старее")

        try:
            manager = self._get_manager()

            result = manager._is_newer("1.1.0", "1.2.0")
            self.logger.check(
                result is False,
                "1.1.0 < 1.2.0: _is_newer() = False",
                f"1.1.0 < 1.2.0: _is_newer() вернул {result}"
            )

            result_2 = manager._is_newer("0.9.499", "0.9.500")
            self.logger.check(
                result_2 is False,
                "0.9.499 < 0.9.500: _is_newer() = False",
                f"0.9.499 < 0.9.500: _is_newer() вернул {result_2}"
            )

        except Exception as e:
            self.logger.error(f"is_newer (remote старее): {e}")

    def test_12_same_version(self) -> None:
        """TEST 12: _is_newer -- одинаковые версии"""
        self.logger.section("12. is_newer: одинаковые версии")

        try:
            manager = self._get_manager()

            result = manager._is_newer("1.1.0", "1.1.0")
            self.logger.check(
                result is False,
                "1.1.0 == 1.1.0: _is_newer() = False",
                f"1.1.0 == 1.1.0: _is_newer() вернул {result}"
            )

            result_2 = manager._is_newer("0.9.500", "0.9.500")
            self.logger.check(
                result_2 is False,
                "0.9.500 == 0.9.500: _is_newer() = False",
                f"0.9.500 == 0.9.500: _is_newer() вернул {result_2}"
            )

        except Exception as e:
            self.logger.error(f"is_newer (одинаковые): {e}")

    def test_13_malformed_version(self) -> None:
        """TEST 13: _is_newer -- невалидные строки версий"""
        self.logger.section("13. is_newer: невалидные версии")

        try:
            manager = self._get_manager()

            # Нечисловые компоненты
            result = manager._is_newer("abc", "1.0.0")
            self.logger.check(
                result is False,
                "abc vs 1.0.0: _is_newer() = False (graceful)",
                f"abc vs 1.0.0: _is_newer() вернул {result}"
            )

            # Пустая строка
            result_2 = manager._is_newer("", "1.0.0")
            self.logger.check(
                result_2 is False,
                "'' vs 1.0.0: _is_newer() = False (graceful)",
                f"'' vs 1.0.0: _is_newer() вернул {result_2}"
            )

            # None (AttributeError ветка)
            result_3 = manager._is_newer(None, "1.0.0")
            self.logger.check(
                result_3 is False,
                "None vs 1.0.0: _is_newer() = False (graceful)",
                f"None vs 1.0.0: _is_newer() вернул {result_3}"
            )

            # Специальные символы
            result_4 = manager._is_newer("1.0.0-beta", "1.0.0")
            self.logger.check(
                result_4 is False,
                "1.0.0-beta vs 1.0.0: _is_newer() = False (graceful)",
                f"1.0.0-beta vs 1.0.0: _is_newer() вернул {result_4}"
            )

        except Exception as e:
            self.logger.error(f"is_newer (невалидные): {e}")
