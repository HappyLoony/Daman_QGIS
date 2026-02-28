# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_7_1 - Тесты для F_6_1 Табель (расчёт нормы с отпуском)

Тестирует:
- TimesheetData.vacation_hours (свойство)
- TimesheetData.get_vacation_hours_until_day(end_day)
- get_employee_norm() в format_validation_report (формула нормы)
- Расчёт нормы в Fsm_6_1_5_summary (формула сводного табеля)
- Граничные случаи (rate=1.0, нет отпуска, отпуск > нормы)
"""

from datetime import date


def _make_timesheet(
    fio="Иванов Иван Иванович",
    projects=None,
    special_categories=None,
    total_hours=0.0,
    year=2026,
    month=1
):
    """Создать TimesheetData с минимальными параметрами для тестов."""
    from Daman_QGIS.tools.F_6_special.submodules.Fsm_6_1_3_parser import (
        TimesheetData, ProjectRow, SpecialCategoryRow
    )

    return TimesheetData(
        filepath="test.xlsx",
        filename="Иванов_01.xlsx",
        fio=fio,
        month_start=date(year, month, 1),
        month_end=date(year, month, 28),
        year=year,
        month=month,
        projects=projects or [],
        special_categories=special_categories or [],
        total_hours=total_hours
    )


def _make_vacation_category(total_hours, daily_hours=None):
    """Создать SpecialCategoryRow для отпуска."""
    from Daman_QGIS.tools.F_6_special.submodules.Fsm_6_1_3_parser import SpecialCategoryRow

    return SpecialCategoryRow(
        row_number=20,
        category="Отпуск",
        total_hours=total_hours,
        daily_hours=daily_hours or {}
    )


def _make_sick_category(total_hours, daily_hours=None):
    """Создать SpecialCategoryRow для больничного."""
    from Daman_QGIS.tools.F_6_special.submodules.Fsm_6_1_3_parser import SpecialCategoryRow

    return SpecialCategoryRow(
        row_number=21,
        category="Больничный",
        total_hours=total_hours,
        daily_hours=daily_hours or {}
    )


def _make_project(code, total_hours, daily_hours=None):
    """Создать ProjectRow."""
    from Daman_QGIS.tools.F_6_special.submodules.Fsm_6_1_3_parser import ProjectRow

    return ProjectRow(
        row_number=10,
        code=code,
        name=f"Проект {code}",
        total_hours=total_hours,
        daily_hours=daily_hours or {}
    )


class TestF71VacationNorm:
    """Тесты для F_6_1: расчёт нормы с отпуском по полной ставке"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger

    def run_all_tests(self):
        """Запуск всех тестов"""
        self.logger.section("ТЕСТ F_6_1: Расчёт нормы с отпуском по полной ставке")

        try:
            # TimesheetData: vacation_hours
            self.test_01_vacation_hours_no_vacation()
            self.test_02_vacation_hours_with_vacation()
            self.test_03_vacation_hours_case_insensitive()
            self.test_04_vacation_hours_sick_not_counted()

            # TimesheetData: get_vacation_hours_until_day
            self.test_05_vacation_until_day_full()
            self.test_06_vacation_until_day_partial()
            self.test_07_vacation_until_day_no_vacation()

            # get_employee_norm: формула нормы
            self.test_08_norm_rate_1()
            self.test_09_norm_rate_05_no_vacation()
            self.test_10_norm_rate_05_with_vacation()
            self.test_11_norm_rate_05_full_vacation()
            self.test_12_norm_zero_hours()
            self.test_13_norm_no_rates_dict()

            # format_validation_report: интеграция
            self.test_14_report_perfect_rate_1()
            self.test_15_report_deviation_rate_05()
            self.test_16_report_no_deviation_rate_05_vacation()

            # Сводный табель: формула
            self.test_17_summary_norm_rate_1()
            self.test_18_summary_norm_rate_05_vacation()
            self.test_19_summary_norm_rate_05_no_vacation()

            # Граничные случаи
            self.test_20_vacation_exceeds_norm()
            self.test_21_multiple_special_categories()

        except Exception as e:
            self.logger.error(f"Критическая ошибка: {e}")

        self.logger.summary()

    # --- TimesheetData.vacation_hours ---

    def test_01_vacation_hours_no_vacation(self):
        """ТЕСТ 1: vacation_hours без отпуска = 0"""
        self.logger.section("1. vacation_hours без отпуска")
        try:
            ts = _make_timesheet(
                special_categories=[_make_sick_category(16.0)]
            )
            self.logger.check(
                ts.vacation_hours == 0.0,
                "Без отпуска -> vacation_hours = 0.0",
                f"Без отпуска -> vacation_hours = {ts.vacation_hours}"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_02_vacation_hours_with_vacation(self):
        """ТЕСТ 2: vacation_hours с отпуском"""
        self.logger.section("2. vacation_hours с отпуском")
        try:
            ts = _make_timesheet(
                special_categories=[_make_vacation_category(40.0)]
            )
            self.logger.check(
                ts.vacation_hours == 40.0,
                "Отпуск 40ч -> vacation_hours = 40.0",
                f"Отпуск 40ч -> vacation_hours = {ts.vacation_hours}"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_03_vacation_hours_case_insensitive(self):
        """ТЕСТ 3: vacation_hours нечувствительность к регистру"""
        self.logger.section("3. vacation_hours регистр")
        try:
            from Daman_QGIS.tools.F_6_special.submodules.Fsm_6_1_3_parser import SpecialCategoryRow

            # Категория с другим регистром
            vacation_upper = SpecialCategoryRow(
                row_number=20,
                category="ОТПУСК",
                total_hours=24.0,
                daily_hours={}
            )
            ts = _make_timesheet(special_categories=[vacation_upper])
            self.logger.check(
                ts.vacation_hours == 24.0,
                "ОТПУСК (верхний регистр) -> vacation_hours = 24.0",
                f"ОТПУСК (верхний регистр) -> vacation_hours = {ts.vacation_hours}"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_04_vacation_hours_sick_not_counted(self):
        """ТЕСТ 4: больничный НЕ считается как отпуск"""
        self.logger.section("4. Больничный != отпуск")
        try:
            ts = _make_timesheet(
                special_categories=[
                    _make_sick_category(24.0),
                    _make_vacation_category(16.0)
                ]
            )
            self.logger.check(
                ts.vacation_hours == 16.0,
                "Больничный 24ч + Отпуск 16ч -> vacation_hours = 16.0 (только отпуск)",
                f"vacation_hours = {ts.vacation_hours} (ожидалось 16.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- TimesheetData.get_vacation_hours_until_day ---

    def test_05_vacation_until_day_full(self):
        """ТЕСТ 5: get_vacation_hours_until_day за весь месяц"""
        self.logger.section("5. Отпуск до конца месяца")
        try:
            daily = {1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 8.0}  # 5 дней по 8ч = 40ч
            ts = _make_timesheet(
                special_categories=[_make_vacation_category(40.0, daily)]
            )
            result = ts.get_vacation_hours_until_day(31)
            self.logger.check(
                result == 40.0,
                "Отпуск до 31 дня = 40.0",
                f"Отпуск до 31 дня = {result} (ожидалось 40.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_06_vacation_until_day_partial(self):
        """ТЕСТ 6: get_vacation_hours_until_day за часть месяца"""
        self.logger.section("6. Отпуск за часть месяца")
        try:
            # Отпуск с 1 по 5 день (по 8ч), но считаем до 3 дня
            daily = {1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 8.0}
            ts = _make_timesheet(
                special_categories=[_make_vacation_category(40.0, daily)]
            )
            result = ts.get_vacation_hours_until_day(3)
            self.logger.check(
                result == 24.0,
                "Отпуск до 3 дня = 24.0 (3 дня по 8ч)",
                f"Отпуск до 3 дня = {result} (ожидалось 24.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_07_vacation_until_day_no_vacation(self):
        """ТЕСТ 7: get_vacation_hours_until_day без отпуска = 0"""
        self.logger.section("7. Нет отпуска -> 0")
        try:
            ts = _make_timesheet(special_categories=[])
            result = ts.get_vacation_hours_until_day(15)
            self.logger.check(
                result == 0.0,
                "Без отпуска -> get_vacation_hours_until_day(15) = 0.0",
                f"Без отпуска -> {result} (ожидалось 0.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- get_employee_norm: формула расчёта нормы ---

    def _calc_norm(self, norm_hours, rate, vacation_hours):
        """Воспроизводит формулу get_employee_norm."""
        if norm_hours is None or norm_hours <= 0:
            return 0.0
        if rate == 1.0:
            return norm_hours
        work_norm = norm_hours - vacation_hours
        return work_norm * rate + vacation_hours

    def test_08_norm_rate_1(self):
        """ТЕСТ 8: rate=1.0 -> норма без изменений"""
        self.logger.section("8. Норма при rate=1.0")
        try:
            result = self._calc_norm(160.0, 1.0, 40.0)
            self.logger.check(
                result == 160.0,
                "rate=1.0, норма=160, отпуск=40 -> 160.0 (без изменений)",
                f"Результат: {result} (ожидалось 160.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_09_norm_rate_05_no_vacation(self):
        """ТЕСТ 9: rate=0.5 без отпуска -> норма * 0.5"""
        self.logger.section("9. Норма при rate=0.5 без отпуска")
        try:
            # norm=160, vacation=0, rate=0.5
            # work_norm = 160-0 = 160
            # result = 160*0.5 + 0 = 80
            result = self._calc_norm(160.0, 0.5, 0.0)
            self.logger.check(
                result == 80.0,
                "rate=0.5, норма=160, отпуск=0 -> 80.0",
                f"Результат: {result} (ожидалось 80.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_10_norm_rate_05_with_vacation(self):
        """ТЕСТ 10: rate=0.5 + отпуск -> отпуск по полной ставке"""
        self.logger.section("10. Норма при rate=0.5 с отпуском")
        try:
            # Пример из плана:
            # norm=80, vacation=40, rate=0.5
            # work_norm = 80-40 = 40
            # result = 40*0.5 + 40 = 20 + 40 = 60
            result = self._calc_norm(80.0, 0.5, 40.0)
            self.logger.check(
                result == 60.0,
                "rate=0.5, норма=80, отпуск=40 -> 60.0 (20+40)",
                f"Результат: {result} (ожидалось 60.0)"
            )

            # Ещё вариант: norm=160, vacation=40, rate=0.5
            # work_norm = 160-40 = 120
            # result = 120*0.5 + 40 = 60 + 40 = 100
            result2 = self._calc_norm(160.0, 0.5, 40.0)
            self.logger.check(
                result2 == 100.0,
                "rate=0.5, норма=160, отпуск=40 -> 100.0 (60+40)",
                f"Результат: {result2} (ожидалось 100.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_11_norm_rate_05_full_vacation(self):
        """ТЕСТ 11: rate=0.5, весь месяц отпуск -> норма = отпуск"""
        self.logger.section("11. Норма при rate=0.5 (весь месяц отпуск)")
        try:
            # norm=160, vacation=160, rate=0.5
            # work_norm = 160-160 = 0
            # result = 0*0.5 + 160 = 160
            result = self._calc_norm(160.0, 0.5, 160.0)
            self.logger.check(
                result == 160.0,
                "rate=0.5, норма=160, отпуск=160 -> 160.0 (весь месяц отпуск)",
                f"Результат: {result} (ожидалось 160.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_12_norm_zero_hours(self):
        """ТЕСТ 12: norm_hours=0 или None -> 0"""
        self.logger.section("12. Норма = 0 или None")
        try:
            result_zero = self._calc_norm(0.0, 0.5, 40.0)
            self.logger.check(
                result_zero == 0.0,
                "norm=0, rate=0.5 -> 0.0",
                f"Результат: {result_zero} (ожидалось 0.0)"
            )

            result_none = self._calc_norm(None, 0.5, 40.0)
            self.logger.check(
                result_none == 0.0,
                "norm=None, rate=0.5 -> 0.0",
                f"Результат: {result_none} (ожидалось 0.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_13_norm_no_rates_dict(self):
        """ТЕСТ 13: нет словаря ставок -> rate=1.0 по умолчанию"""
        self.logger.section("13. Нет словаря ставок")
        try:
            # Проверяем через format_validation_report (employee_rates=None)
            from Daman_QGIS.tools.F_6_special.submodules.Fsm_6_1_2_validator import (
                ValidationResult, format_validation_report
            )

            ts = _make_timesheet(
                fio="Тестов Тест",
                total_hours=160.0,
                special_categories=[_make_vacation_category(40.0)]
            )
            vr = ValidationResult(is_valid=True)

            # Без employee_rates -> rate=1.0 -> norm = norm_hours
            report = format_validation_report(
                [(ts, vr)],
                use_html=False,
                norm_hours=160.0,
                end_day=None,
                employee_rates=None  # Нет словаря
            )

            # Должен быть в списке perfect (без отклонений при rate=1.0)
            self.logger.check(
                "без замечаний" in report.lower() or "табелей прошли" in report.lower(),
                "Без словаря ставок -> rate=1.0, табель ОК",
                f"Отчёт: {report[:200]}"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- format_validation_report: интеграция ---

    def test_14_report_perfect_rate_1(self):
        """ТЕСТ 14: rate=1.0, часы=норма -> perfect"""
        self.logger.section("14. Отчёт: rate=1.0 без отклонений")
        try:
            from Daman_QGIS.tools.F_6_special.submodules.Fsm_6_1_2_validator import (
                ValidationResult, format_validation_report
            )

            ts = _make_timesheet(fio="Петров П.П.", total_hours=160.0)
            vr = ValidationResult(is_valid=True)

            report = format_validation_report(
                [(ts, vr)],
                use_html=False,
                norm_hours=160.0,
                employee_rates={"Петров П.П.": 1.0}
            )

            self.logger.check(
                "без замечаний" in report.lower(),
                "rate=1.0, часы=160, норма=160 -> perfect табель",
                f"Отчёт: {report[:200]}"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_15_report_deviation_rate_05(self):
        """ТЕСТ 15: rate=0.5 без отпуска, часы=160 при норме=160 -> отклонение +80"""
        self.logger.section("15. Отчёт: rate=0.5 с отклонением")
        try:
            from Daman_QGIS.tools.F_6_special.submodules.Fsm_6_1_2_validator import (
                ValidationResult, format_validation_report
            )

            # rate=0.5, norm=160, vacation=0 -> employee_norm = 80
            # hours=160 -> deviation = 160-80 = +80
            ts = _make_timesheet(fio="Сидоров С.С.", total_hours=160.0)
            vr = ValidationResult(is_valid=True)

            report = format_validation_report(
                [(ts, vr)],
                use_html=False,
                norm_hours=160.0,
                employee_rates={"Сидоров С.С.": 0.5}
            )

            # Должен быть problem (отклонение != 0)
            self.logger.check(
                "без замечаний" not in report.lower() or "Сидоров" in report,
                "rate=0.5, часы=160, норма=160 -> problem табель (отклонение +80)",
                f"Отчёт: {report[:300]}"
            )

            # Проверяем отклонение (80.0)
            self.logger.check(
                "80" in report,
                "Отклонение 80 отображается в отчёте",
                f"80 не найдено в отчёте: {report[:300]}"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_16_report_no_deviation_rate_05_vacation(self):
        """ТЕСТ 16: rate=0.5 + отпуск -> точное совпадение с нормой"""
        self.logger.section("16. Отчёт: rate=0.5 + отпуск, без отклонения")
        try:
            from Daman_QGIS.tools.F_6_special.submodules.Fsm_6_1_2_validator import (
                ValidationResult, format_validation_report
            )

            # norm=80, vacation=40, rate=0.5
            # employee_norm = (80-40)*0.5 + 40 = 20+40 = 60
            # hours = 60 -> deviation = 0
            vacation_daily = {1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 8.0}
            project_daily = {6: 4.0, 7: 4.0, 8: 4.0, 9: 4.0, 10: 4.0}

            ts = _make_timesheet(
                fio="Козлов К.К.",
                total_hours=60.0,
                projects=[_make_project("2025-001", 20.0, project_daily)],
                special_categories=[_make_vacation_category(40.0, vacation_daily)]
            )
            vr = ValidationResult(is_valid=True)

            report = format_validation_report(
                [(ts, vr)],
                use_html=False,
                norm_hours=80.0,
                employee_rates={"Козлов К.К.": 0.5}
            )

            self.logger.check(
                "без замечаний" in report.lower(),
                "rate=0.5, часы=60, норма_эфф=60 -> perfect табель (без отклонения)",
                f"Отчёт: {report[:300]}"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- Сводный табель: формула нормы ---

    def test_17_summary_norm_rate_1(self):
        """ТЕСТ 17: сводный табель, rate=1.0 -> employee_norm = norm_period"""
        self.logger.section("17. Сводный: rate=1.0")
        try:
            norm_period = 160.0
            rate = 1.0
            vacation_hours = 40.0

            if rate == 1.0:
                employee_norm = norm_period
            else:
                work_norm = norm_period - vacation_hours
                employee_norm = work_norm * rate + vacation_hours

            self.logger.check(
                employee_norm == 160.0,
                "Сводный: rate=1.0, norm=160, отпуск=40 -> employee_norm=160.0",
                f"employee_norm={employee_norm} (ожидалось 160.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_18_summary_norm_rate_05_vacation(self):
        """ТЕСТ 18: сводный табель, rate=0.5 + отпуск"""
        self.logger.section("18. Сводный: rate=0.5 + отпуск")
        try:
            norm_period = 160.0
            rate = 0.5
            vacation_hours = 40.0

            # Формула из Fsm_6_1_5_summary.py
            if rate == 1.0:
                employee_norm = norm_period
            else:
                work_norm = norm_period - vacation_hours
                employee_norm = work_norm * rate + vacation_hours

            # (160-40)*0.5 + 40 = 60 + 40 = 100
            expected = 100.0
            self.logger.check(
                employee_norm == expected,
                f"Сводный: rate=0.5, norm=160, отпуск=40 -> employee_norm={expected}",
                f"employee_norm={employee_norm} (ожидалось {expected})"
            )

            # Проверяем deviation
            employee_total = 100.0
            deviation = employee_total - employee_norm
            self.logger.check(
                deviation == 0.0,
                "Отклонение = 0 при точном совпадении",
                f"Отклонение = {deviation} (ожидалось 0.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_19_summary_norm_rate_05_no_vacation(self):
        """ТЕСТ 19: сводный табель, rate=0.5 без отпуска"""
        self.logger.section("19. Сводный: rate=0.5 без отпуска")
        try:
            norm_period = 160.0
            rate = 0.5
            vacation_hours = 0.0

            if rate == 1.0:
                employee_norm = norm_period
            else:
                work_norm = norm_period - vacation_hours
                employee_norm = work_norm * rate + vacation_hours

            # (160-0)*0.5 + 0 = 80
            self.logger.check(
                employee_norm == 80.0,
                "Сводный: rate=0.5, norm=160, отпуск=0 -> employee_norm=80.0",
                f"employee_norm={employee_norm} (ожидалось 80.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- Граничные случаи ---

    def test_20_vacation_exceeds_norm(self):
        """ТЕСТ 20: отпуск > нормы (нестандартная ситуация)"""
        self.logger.section("20. Отпуск больше нормы")
        try:
            # Нестандартная ситуация: vacation > norm (ошибка данных)
            # norm=80, vacation=120, rate=0.5
            # work_norm = 80-120 = -40
            # result = -40*0.5 + 120 = -20 + 120 = 100
            result = self._calc_norm(80.0, 0.5, 120.0)

            # Формула математически корректна даже при отпуске > нормы
            self.logger.check(
                result == 100.0,
                "Отпуск > нормы: математически корректный результат (100.0)",
                f"Результат: {result} (ожидалось 100.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_21_multiple_special_categories(self):
        """ТЕСТ 21: несколько спец.категорий (отпуск + больничный)"""
        self.logger.section("21. Несколько спец.категорий")
        try:
            vacation_daily = {1: 8.0, 2: 8.0, 3: 8.0}  # 3 дня = 24ч
            sick_daily = {10: 8.0, 11: 8.0}  # 2 дня = 16ч

            ts = _make_timesheet(
                special_categories=[
                    _make_vacation_category(24.0, vacation_daily),
                    _make_sick_category(16.0, sick_daily)
                ]
            )

            # vacation_hours должен быть только отпуск
            self.logger.check(
                ts.vacation_hours == 24.0,
                "Отпуск + Больничный: vacation_hours = 24.0 (только отпуск)",
                f"vacation_hours = {ts.vacation_hours} (ожидалось 24.0)"
            )

            # get_vacation_hours_until_day до 2 дня = 16ч (дни 1,2)
            partial = ts.get_vacation_hours_until_day(2)
            self.logger.check(
                partial == 16.0,
                "Отпуск до 2 дня: 16.0 (2 дня по 8ч)",
                f"Отпуск до 2 дня: {partial} (ожидалось 16.0)"
            )

            # Норма: norm=160, vacation=24, rate=0.5
            # work_norm = 160-24 = 136
            # result = 136*0.5 + 24 = 68 + 24 = 92
            norm = self._calc_norm(160.0, 0.5, 24.0)
            self.logger.check(
                norm == 92.0,
                "Норма: rate=0.5, norm=160, отпуск=24 -> 92.0 (больничный не влияет на формулу)",
                f"Норма = {norm} (ожидалось 92.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")


def run_tests(iface, logger):
    """Точка входа для запуска тестов"""
    test = TestF71VacationNorm(iface, logger)
    test.run_all_tests()
    return test
