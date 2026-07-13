# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_49 — Тесты M_49 FontManager / _font_canon (канон шрифтов).

Покрытие (этап 5 плана 2026-06-04-M_49-font-manager-centralization):
- parse_font_style: все исторические форматы БД — 'Bold Italic'
  (Base_labels.json), 'bold;italic' / 'regular ' с trailing space
  (Base_layout.json), '' / None / '-', смешанный регистр (M3)
- get_family: все роли FontRole
- get_family_for_doc_type: 'ДПТ' / 'Мастер-план' / неизвестный
  (fallback DRAWING)
- dxf_label_text_style: ключи name/font_file/family/bold/italic
  и значения канона
- required_font_files: 11 файлов (4 GOST + 5 Avenir + 2 IBM Plex),
  без OpenSans
- ensure_registered (FontManager через registry.get('M_49')):
  канон-роль возвращает bool без исключений; не-канонная family — False
"""

from typing import Any, List, Optional, Tuple


class TestFsm4249:
    """Тесты канона шрифтов M_49 (_font_canon + FontManager)."""

    def __init__(self, iface: Any, logger: Any) -> None:
        self.iface = iface
        self.logger = logger

    def run_all_tests(self) -> None:
        """Entry point для comprehensive runner."""
        self.logger.section("ТЕСТ M_49: FontManager / _font_canon")

        try:
            self.test_01_import()
            self.test_02_parse_font_style_formats()
            self.test_03_get_family_all_roles()
            self.test_04_get_family_for_doc_type()
            self.test_05_dxf_label_text_style()
            self.test_06_required_font_files()
            self.test_07_ensure_registered()
        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов M_49: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    # === Группа 1: Импорт ===

    def test_01_import(self) -> None:
        """ТЕСТ 1: Импорт _font_canon и наличие API."""
        self.logger.section("1. Импорт _font_canon")
        try:
            from Daman_QGIS.managers.styling import _font_canon

            required_api = [
                'FontRole', 'FAMILIES', 'FONT_FILES',
                'parse_font_style', 'get_family', 'get_family_for_doc_type',
                'dxf_label_text_style', 'required_font_files',
                'excel_font_name', 'word_font_name',
            ]
            missing = [name for name in required_api
                       if not hasattr(_font_canon, name)]
            self.logger.check(
                not missing,
                "_font_canon импортирован, всё API на месте",
                f"Отсутствует API: {missing}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка импорта _font_canon: {e}")

    # === Группа 2: Чистые функции канона ===

    def test_02_parse_font_style_formats(self) -> None:
        """ТЕСТ 2: parse_font_style на всех форматах БД."""
        self.logger.section("2. parse_font_style: форматы БД")
        try:
            from Daman_QGIS.managers.styling import _font_canon

            cases: List[Tuple[Optional[str], Tuple[bool, bool]]] = [
                ('Bold Italic', (True, True)),     # Base_labels.json
                ('bold;italic', (True, True)),     # Base_layout.json
                ('bold;regular ', (True, False)),  # Base_layout, trailing space
                ('regular ', (False, False)),      # Base_layout, trailing space
                ('Italic', (False, True)),
                ('', (False, False)),
                (None, (False, False)),
                ('-', (False, False)),
                ('bold italic', (True, True)),     # смешанный регистр (M3)
            ]
            for value, expected in cases:
                result = _font_canon.parse_font_style(value)
                self.logger.check(
                    result == expected,
                    f"parse_font_style({value!r}) -> {result}",
                    f"parse_font_style({value!r}): ожидалось {expected}, "
                    f"получено {result}",
                )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_03_get_family_all_roles(self) -> None:
        """ТЕСТ 3: get_family для всех ролей канона."""
        self.logger.section("3. get_family: все роли")
        try:
            from Daman_QGIS.managers.styling import _font_canon

            # Литералы — осознанное сравнение со значениями канона
            # (утверждён владельцем 2026-06-04, план M_49)
            expected = {
                _font_canon.FontRole.DRAWING: 'GOST 2.304',
                _font_canon.FontRole.MASTERPLAN: 'Avenir Next W1G',
                _font_canon.FontRole.DOCUMENT: 'Times New Roman',
                _font_canon.FontRole.PLUGIN_UI: 'IBM Plex Sans',
            }
            for role in _font_canon.FontRole:
                family = _font_canon.get_family(role)
                self.logger.check(
                    family == expected[role],
                    f"get_family({role.value}) -> '{family}'",
                    f"get_family({role.value}): ожидалось "
                    f"'{expected[role]}', получено '{family}'",
                )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_04_get_family_for_doc_type(self) -> None:
        """ТЕСТ 4: get_family_for_doc_type (ДПТ / Мастер-план / fallback)."""
        self.logger.section("4. get_family_for_doc_type")
        try:
            from Daman_QGIS.managers.styling import _font_canon

            drawing = _font_canon.get_family(_font_canon.FontRole.DRAWING)
            masterplan = _font_canon.get_family(_font_canon.FontRole.MASTERPLAN)

            cases = [
                ('ДПТ', drawing),
                ('Мастер-план', masterplan),
                # Неизвестный doc_type -> fallback DRAWING (сохранение
                # поведения прежнего DOC_TYPE_FONTS.get(..., 'GOST 2.304'))
                ('Неизвестный вид', drawing),
            ]
            for doc_type, expected in cases:
                family = _font_canon.get_family_for_doc_type(doc_type)
                self.logger.check(
                    family == expected,
                    f"get_family_for_doc_type('{doc_type}') -> '{family}'",
                    f"get_family_for_doc_type('{doc_type}'): ожидалось "
                    f"'{expected}', получено '{family}'",
                )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_05_dxf_label_text_style(self) -> None:
        """ТЕСТ 5: dxf_label_text_style — ключи и значения канона."""
        self.logger.section("5. dxf_label_text_style")
        try:
            from Daman_QGIS.managers.styling import _font_canon

            style = _font_canon.dxf_label_text_style()

            required_keys = {'name', 'font_file', 'family', 'bold', 'italic'}
            self.logger.check(
                required_keys.issubset(style.keys()),
                f"Все ключи на месте: {sorted(required_keys)}",
                f"Отсутствуют ключи: {sorted(required_keys - set(style.keys()))}",
            )

            # Литералы — осознанное сравнение со значениями канона
            # (схема DXF-выносок после фикса 2026-06-04: TTF + extended
            # font data, см. docstring _font_canon)
            expected = {
                'name': 'GOST 2.304 Type B italic',
                'font_file': 'GOST-2.304_Type-B_italic.ttf',
                'family': 'GOST 2.304',
                'bold': True,
                'italic': True,
            }
            for key, value in expected.items():
                self.logger.check(
                    style.get(key) == value,
                    f"style['{key}'] == {value!r}",
                    f"style['{key}']: ожидалось {value!r}, "
                    f"получено {style.get(key)!r}",
                )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_06_required_font_files(self) -> None:
        """ТЕСТ 6: required_font_files — 11 файлов канона, без OpenSans."""
        self.logger.section("6. required_font_files")
        try:
            from Daman_QGIS.managers.styling import _font_canon

            files = _font_canon.required_font_files()

            self.logger.check(
                len(files) == 11,
                f"Канон-список: {len(files)} файлов (4 GOST + 5 Avenir + 2 IBM Plex)",
                f"Ожидалось 11 файлов, получено {len(files)}: {files}",
            )

            gost_count = sum(1 for f in files if f.lower().startswith('gost'))
            avenir_count = sum(1 for f in files if f.startswith('Avenir'))
            plex_count = sum(1 for f in files if f.startswith('IBMPlexSans'))
            self.logger.check(
                (gost_count, avenir_count, plex_count) == (4, 5, 2),
                f"Состав по ролям: GOST={gost_count}, Avenir={avenir_count}, "
                f"IBMPlex={plex_count}",
                f"Неверный состав: GOST={gost_count} (ожидалось 4), "
                f"Avenir={avenir_count} (5), IBMPlex={plex_count} (2)",
            )

            opensans = [f for f in files if 'opensans' in f.lower()]
            self.logger.check(
                not opensans,
                "OpenSans в канон-списке отсутствует (легаси исключено)",
                f"В канон-списке найдено легаси OpenSans: {opensans}",
            )

            ttf_only = all(f.lower().endswith('.ttf') for f in files)
            self.logger.check(
                ttf_only,
                "Все файлы канона — .ttf",
                f"Найдены не-ttf файлы: "
                f"{[f for f in files if not f.lower().endswith('.ttf')]}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === Группа 3: Stateful (FontManager через registry) ===

    def test_07_ensure_registered(self) -> None:
        """ТЕСТ 7: ensure_registered через registry.get('M_49')."""
        self.logger.section("7. ensure_registered (M_49)")
        try:
            from Daman_QGIS.managers import registry
            from Daman_QGIS.managers.styling import _font_canon

            mgr = registry.get('M_49')
            if mgr is None:
                self.logger.fail("registry.get('M_49') вернул None")
                return

            # Канон-роль: bool без исключений (True/False зависит от
            # установленных шрифтов среды — не фиксируем значение)
            result = mgr.ensure_registered(_font_canon.FontRole.DRAWING)
            self.logger.check(
                isinstance(result, bool),
                f"ensure_registered(DRAWING) -> {result} (bool, без исключений)",
                f"ensure_registered(DRAWING) вернул не-bool: {result!r}",
            )

            # Канон-family строкой: тоже bool без исключений
            family = _font_canon.get_family(_font_canon.FontRole.DRAWING)
            result_str = mgr.ensure_registered(family)
            self.logger.check(
                isinstance(result_str, bool),
                f"ensure_registered('{family}') -> {result_str} (bool)",
                f"ensure_registered('{family}') вернул не-bool: {result_str!r}",
            )

            # Не-канонная family: регистрация пропускается, строго False
            result_alien = mgr.ensure_registered('Daman_No_Such_Family_T49')
            self.logger.check(
                result_alien is False,
                "Не-канонная family -> False (регистрация пропущена)",
                f"Не-канонная family: ожидалось False, "
                f"получено {result_alien!r}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")
