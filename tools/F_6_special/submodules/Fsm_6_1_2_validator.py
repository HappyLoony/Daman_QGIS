# -*- coding: utf-8 -*-
"""
Валидатор табелей сотрудников.

Проверяет:
- Формат имени файла (Фамилия_MM.xlsx)
- ФИО сотрудника (соответствие базе и файлу)
- Месяц табеля (текущий месяц)
- Шифры проектов (наличие в справочнике)
- Заполненность рабочих дней
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Set, Tuple

from Daman_QGIS.utils import (
    log_info, log_warning, log_error, normalize_for_classification
)
from Daman_QGIS.managers.reference import EmployeeReferenceManager
from Daman_QGIS.managers.reference.submodules import ProductionCalendarManager
from .Fsm_6_1_3_parser import TimesheetData, SPECIAL_CATEGORIES, load_valid_project_codes
from .Fsm_6_1_6_norm import compute_employee_norm, absence_by_day, ABSENCE

# Нормализованное+lowercase множество ВСЕХ отсутствий (ABSENCE = отпуск/
# больничный/отгул) для устойчивого отбора absence-категорий в validate_overtime
# (пропуск per-day переработки) и validate_absence_placement (отбраковка
# аномального заполнения). Отбор через normalize_for_classification -- parser
# несёт невидимые символы из Excel (nbsp/zero-width), голый .lower() промахнётся
# (как C0/C3). Отличие от _NEUTRALIZING_NORM (норма): ABSENCE включает отгул --
# он тоже отсутствие (не работа), но выкупает норму, а не нейтрализует.
_ABSENCE_CLASSIFY = {normalize_for_classification(c).lower() for c in ABSENCE}


@dataclass
class ValidationMessage:
    """Сообщение валидации."""
    level: str  # "ERROR", "WARNING", "INFO"
    message: str
    row: Optional[int] = None


@dataclass
class ValidationResult:
    """Результат валидации табеля."""
    is_valid: bool
    messages: List[ValidationMessage] = field(default_factory=list)
    errors_count: int = 0
    warnings_count: int = 0

    def add_error(self, message: str, row: Optional[int] = None) -> None:
        """Добавить ошибку."""
        self.messages.append(ValidationMessage("ERROR", message, row))
        self.errors_count += 1
        self.is_valid = False

    def add_warning(self, message: str, row: Optional[int] = None) -> None:
        """Добавить предупреждение."""
        self.messages.append(ValidationMessage("WARNING", message, row))
        self.warnings_count += 1

    def add_info(self, message: str, row: Optional[int] = None) -> None:
        """Добавить информационное сообщение."""
        self.messages.append(ValidationMessage("INFO", message, row))

    def merge(self, other: 'ValidationResult') -> None:
        """Объединить с другим результатом валидации."""
        self.messages.extend(other.messages)
        self.errors_count += other.errors_count
        self.warnings_count += other.warnings_count
        if not other.is_valid:
            self.is_valid = False


class TimesheetValidator:
    """Валидатор табелей сотрудников."""

    # Паттерн имени файла: Фамилия_MM.xlsx или Фамилия_M.xlsx
    FILENAME_PATTERN = re.compile(r'^([А-Яа-яЁё]+)_(\d{1,2})\.xlsx$', re.UNICODE)

    def __init__(self, target_month: int, target_year: int, end_day: Optional[int] = None):
        """
        Инициализация валидатора.

        Args:
            target_month: Целевой месяц (1-12). ОБЯЗАТЕЛЬНЫЙ (GUI всегда даёт).
            target_year: Целевой год. ОБЯЗАТЕЛЬНЫЙ (GUI всегда даёт).
            end_day: Последний день для расчётов (включительно).
                     Если None - последний день месяца.

        Note:
            target_month/target_year -- required (без дефолта на now(), FIX-4/
            OPT-015): дефолт на now().year давал ложную отбраковку декабря в
            январе; None-дефолт ломал бы missing_timesheet-путь (f"{None:02d}").
            GUI всегда передаёт оба (F_6_1_timesheet:313) -> fail-closed симметрия.
        """
        self._target_month = target_month
        self._target_year = target_year
        self._end_day = end_day  # None означает весь месяц
        self._employee_manager: Optional[EmployeeReferenceManager] = None
        self._valid_project_codes: Optional[Set[str]] = None
        self._calendar_manager: Optional[ProductionCalendarManager] = None
        self._employees_cache: Optional[List[dict]] = None
        self._surnames_cache: Optional[Set[str]] = None

    @property
    def employee_manager(self) -> EmployeeReferenceManager:
        """Ленивая инициализация менеджера сотрудников."""
        if self._employee_manager is None:
            self._employee_manager = EmployeeReferenceManager()
        return self._employee_manager

    @property
    def valid_project_codes(self) -> Set[str]:
        """Ленивая загрузка валидных шифров проектов из сетевого справочника."""
        if self._valid_project_codes is None:
            self._valid_project_codes = load_valid_project_codes()
        return self._valid_project_codes

    @property
    def calendar_manager(self) -> ProductionCalendarManager:
        """Ленивая инициализация менеджера производственного календаря."""
        if self._calendar_manager is None:
            self._calendar_manager = ProductionCalendarManager()
        return self._calendar_manager

    def _get_employees(self) -> List[dict]:
        """Получить список сотрудников с кэшированием."""
        if self._employees_cache is None:
            self._employees_cache = self.employee_manager.get_employees()
        return self._employees_cache

    def _get_surnames_set(self) -> Set[str]:
        """Получить множество фамилий для быстрой проверки."""
        if self._surnames_cache is None:
            employees = self._get_employees()
            self._surnames_cache = {
                emp.get('last_name', '').lower()
                for emp in employees
                if emp.get('last_name')
            }
        return self._surnames_cache

    def _find_employee_by_fio(self, fio: str) -> Optional[dict]:
        """
        Найти сотрудника по ФИО (полному или сокращённому).

        Поддерживает форматы:
        - Полное: "Иванов Иван Иванович"
        - Сокращённое: "Иванов И.И." или "Иванов И. И."

        Args:
            fio: ФИО сотрудника

        Returns:
            Данные сотрудника или None
        """
        if not fio:
            return None

        # Нормализуем ФИО: убираем лишние пробелы, приводим к нижнему регистру
        fio_normalized = ' '.join(fio.lower().strip().split())
        employees = self._get_employees()

        for emp in employees:
            # Проверяем полное ФИО
            full_name = self.employee_manager.get_employee_full_name(emp, format='full')
            if full_name.lower() == fio_normalized:
                return emp

            # Проверяем сокращённое ФИО (Иванов И.И.)
            short_name = self.employee_manager.get_employee_full_name(emp, format='short')
            # Нормализуем: "Иванов И.И." и "Иванов И. И." должны совпадать
            short_normalized = ' '.join(short_name.lower().split())
            if short_normalized == fio_normalized:
                return emp

            # Дополнительно: проверка без точек (на случай "Иванов ИИ")
            fio_no_dots = fio_normalized.replace('.', '').replace(' ', '')
            short_no_dots = short_name.lower().replace('.', '').replace(' ', '')
            if fio_no_dots == short_no_dots:
                return emp

        return None

    def _find_employee_by_surname(self, surname: str) -> Optional[dict]:
        """
        Найти сотрудника по фамилии.

        Args:
            surname: Фамилия

        Returns:
            Данные сотрудника или None (если несколько - возвращает первого)
        """
        if not surname:
            return None

        surname_lower = surname.lower().strip()
        employees = self._get_employees()

        for emp in employees:
            if emp.get('last_name', '').lower() == surname_lower:
                return emp

        return None

    def get_employee_rate(self, fio: str) -> float:
        """
        Получить ставку сотрудника по ФИО.

        Args:
            fio: ФИО сотрудника (полное или сокращённое)

        Returns:
            Ставка сотрудника (1.0 по умолчанию)
        """
        employee = self._find_employee_by_fio(fio)
        if employee:
            return self.employee_manager.get_employee_rate(employee)
        return 1.0

    def get_target_month(self) -> int:
        """
        Получить целевой месяц для обработки табелей.

        Returns:
            Номер целевого месяца (1-12)
        """
        return self._target_month

    def get_target_year(self) -> int:
        """
        Получить целевой год для обработки табелей.

        Returns:
            Целевой год (из GUI, authoritative)
        """
        return self._target_year

    def get_end_day(self, year: int, month: int) -> int:
        """
        Получить последний день для расчётов.

        Args:
            year: Год
            month: Месяц

        Returns:
            Последний день для расчётов
        """
        if self._end_day is not None:
            return self._end_day

        # Если не указан - возвращаем последний день месяца
        import calendar
        return calendar.monthrange(year, month)[1]

    def is_valid_month(self, month: int) -> bool:
        """
        Проверить, является ли месяц допустимым (целевой месяц).

        Args:
            month: Номер месяца (1-12)

        Returns:
            True если месяц допустим
        """
        return month == self._target_month

    def validate_filename(self, filename: str) -> ValidationResult:
        """
        Валидация имени файла.

        Args:
            filename: Имя файла (например, "Иванов_01.xlsx")

        Returns:
            Результат валидации
        """
        result = ValidationResult(is_valid=True)

        # Проверка расширения
        if not filename.lower().endswith('.xlsx'):
            result.add_error(f"Неверное расширение файла: ожидается .xlsx")
            return result

        # Проверка формата
        match = self.FILENAME_PATTERN.match(filename)
        if not match:
            result.add_error(
                f"Неверный формат имени файла: ожидается Фамилия_НомерМесяца.xlsx"
            )
            return result

        surname = match.group(1)
        month_str = match.group(2)

        # Проверка месяца
        try:
            month = int(month_str)
            if not 1 <= month <= 12:
                result.add_error(f"Неверный номер месяца: {month_str}")
        except ValueError:
            result.add_error(f"Невозможно распознать номер месяца: {month_str}")

        # Проверка фамилии в базе
        if surname.lower() not in self._get_surnames_set():
            result.add_error(f"Сотрудник с фамилией '{surname}' не найден в базе")

        return result

    def validate_fio(self, timesheet: TimesheetData) -> ValidationResult:
        """
        Валидация ФИО сотрудника.

        Если ФИО не указано в Excel, пытаемся найти сотрудника по фамилии из имени файла.

        Args:
            timesheet: Данные табеля

        Returns:
            Результат валидации
        """
        result = ValidationResult(is_valid=True)

        # Извлекаем фамилию из имени файла
        match = self.FILENAME_PATTERN.match(timesheet.filename)
        filename_surname = match.group(1) if match else None

        if not timesheet.fio:
            # ФИО не указано - пробуем найти по фамилии из имени файла
            if filename_surname:
                # Ищем сотрудника по фамилии из имени файла
                employee = self._find_employee_by_surname(filename_surname)
                if employee:
                    # Заполняем ФИО из базы (предупреждение не нужно - успешно найдено)
                    full_fio = self.employee_manager.get_employee_full_name(employee, format='full')
                    if full_fio:
                        timesheet.fio = full_fio
                else:
                    result.add_error(f"Сотрудник с фамилией '{filename_surname}' не найден в базе")
            else:
                result.add_error("Невозможно определить сотрудника: ФИО не указано и имя файла не соответствует шаблону")
            return result

        # ФИО указано - проверяем соответствие имени файла
        if filename_surname:
            fio_surname = timesheet.surname.lower()
            if filename_surname.lower() != fio_surname:
                result.add_warning(
                    f"ФИО в ячейке A10 ('{timesheet.fio}') не соответствует "
                    f"имени файла ('{timesheet.filename}')"
                )

        # Проверка ФИО в базе
        employee = self._find_employee_by_fio(timesheet.fio)
        if not employee:
            # Пробуем найти по фамилии из файла
            if filename_surname:
                employee = self._find_employee_by_surname(filename_surname)

        if not employee:
            result.add_error(f"Сотрудник не найден в базе: {timesheet.fio}")
        else:
            # Заменяем ФИО на полное из базы (для сводного табеля)
            full_fio = self.employee_manager.get_employee_full_name(employee, format='full')
            if full_fio and full_fio != timesheet.fio:
                timesheet.fio = full_fio

        return result

    def validate_month(self, timesheet: TimesheetData) -> ValidationResult:
        """
        Валидация месяца табеля -- ОТБРАКОВКА невалидных (FIX-4/FIX-5).

        Порядок гейта СТРОГО (R5-5/OPT-011):
        1. month_start is None (B4 не распарсился) -> add_error (отбраковка).
           ПЕРВОЙ: парсер на битом B4 даёт year/month=now() (не None), поэтому
           без None-check-первым битый B4 в том же году ложно прошёл бы.
        2. год+месяц B4 != target_year/target_month -> add_error (отбраковка).
           Число (день) B4 НЕ сравнивается (B4 всегда 1 число).

        Args:
            timesheet: Данные табеля

        Returns:
            Результат валидации (add_error -> is_valid=False -> отбраковка)
        """
        result = ValidationResult(is_valid=True)

        # (1) B4 не распарсился -> отбраковка (fail-closed, FIX-5)
        if timesheet.month_start is None:
            result.add_error("Не удалось определить месяц из ячейки B4")
            return result

        # (2) Несовпадение года+месяца B4 с целевыми (GUI) -> отбраковка (FIX-4)
        target_month = self.get_target_month()
        target_year = self.get_target_year()

        if timesheet.year != target_year or timesheet.month != target_month:
            result.add_error(
                f"Табель за {timesheet.month:02d}.{timesheet.year} не совпадает "
                f"с целевым периодом {target_month:02d}.{target_year}"
            )

        return result

    def validate_project_codes(self, timesheet: TimesheetData) -> ValidationResult:
        """
        Валидация шифров проектов.

        Проверяет шифры по справочнику из сетевого Excel файла
        (ШАБЛОН НЕ УДАЛЯТЬ.xlsx, лист "список проектов").

        Args:
            timesheet: Данные табеля

        Returns:
            Результат валидации
        """
        result = ValidationResult(is_valid=True)

        # Получаем множество валидных шифров (ленивая загрузка)
        valid_codes = self.valid_project_codes

        for project in timesheet.projects:
            code = project.code.strip()

            # Пропускаем пустые шифры
            if not code:
                continue

            # Пропускаем специальные категории (case-insensitive)
            if code.lower() in SPECIAL_CATEGORIES:
                continue

            # Проверяем в справочнике (шифры хранятся в верхнем регистре)
            if code.upper() not in valid_codes:
                result.add_error(
                    f"Неизвестный шифр: '{code}'",
                    row=project.row_number
                )

        return result

    def validate_workdays(self, timesheet: TimesheetData) -> ValidationResult:
        """
        Валидация заполненности рабочих дней.

        Проверяет, что все рабочие дни до указанной даты (end_day) заполнены.

        Args:
            timesheet: Данные табеля

        Returns:
            Результат валидации
        """
        result = ValidationResult(is_valid=True)

        if timesheet.month_start is None:
            return result

        year = timesheet.year
        month = timesheet.month

        # Используем end_day из настроек валидатора
        check_until_day = self.get_end_day(year, month)

        # Получаем рабочие дни для проверки (до end_day включительно).
        # Календарь сетевой: get_workdays_until_date бросает RuntimeError при
        # недоступности. Проверка заполненности (warning-уровень) не должна
        # ронять всю валидацию - при недоступном календаре пропускаем проверку,
        # валидация продолжается, отчёт строится (F-07).
        try:
            workdays = self.calendar_manager.get_workdays_until_date(
                year, month, check_until_day + 1
            )
        except RuntimeError as e:
            log_warning(
                f"Fsm_6_1_2: производственный календарь недоступен, проверка "
                f"заполненности рабочих дней пропущена для {timesheet.fio}: {e}"
            )
            return result

        # Собираем заполненные дни до end_day
        filled_days = timesheet.get_filled_days_until(check_until_day)

        # Проверяем незаполненные рабочие дни
        missing_days = []
        for workday in workdays:
            if workday not in filled_days:
                missing_days.append(workday)

        # Добавляем предупреждения для незаполненных дней
        for day in missing_days[:5]:  # Ограничиваем количество сообщений
            result.add_warning(
                f"Не заполнен рабочий день: {year}-{month:02d}-{day:02d}"
            )

        if len(missing_days) > 5:
            result.add_warning(
                f"... и еще {len(missing_days) - 5} незаполненных рабочих дней"
            )

        return result

    def validate_overtime(self, timesheet: TimesheetData) -> ValidationResult:
        """
        Валидация переработок по дням.

        Выявляет дни с превышением нормы с учётом ставки сотрудника:
        - Обычные рабочие дни: >8*ставка часов
        - Предпраздничные дни: >(8*ставка-1) часов (ст. 95 ТК РФ)
        - Выходные/праздники: любые часы (>0)

        Absence-КАТЕГОРИИ (отпуск/больничный/отгул, ABSENCE) исключаются из
        подсчёта часов дня (ревизия 10, R3): отсутствие -- не работа, само по
        себе per-day переработку не даёт. Рабочие часы того же дня (проекты +
        КП/ОПВ/Обучение) остаются -> частичный день сохраняет легитимную
        переработку по рабочей части. Переработка от отгула проявляется в
        МЕСЯЧНОМ отклонении (выкуп нормы), не здесь.

        Args:
            timesheet: Данные табеля

        Returns:
            Результат валидации с предупреждениями о переработках
        """
        result = ValidationResult(is_valid=True)

        if timesheet.month_start is None:
            return result

        year = timesheet.year
        month = timesheet.month

        # Ставка сотрудника (0.5, 1.0 и т.д.)
        rate = self.get_employee_rate(timesheet.fio)

        # Используем end_day из настроек валидатора
        check_until_day = self.get_end_day(year, month)

        # Собираем часы по дням. Проекты -- всегда работа.
        hours_by_day: Dict[int, float] = {}
        for project in timesheet.projects:
            for day, hours in project.daily_hours.items():
                if day <= check_until_day:
                    hours_by_day[day] = hours_by_day.get(day, 0.0) + hours

        # Спец-категории: пропускаем absence-КАТЕГОРИИ (отпуск/больничный/отгул,
        # ABSENCE), НЕ absence-ДНИ (ревизия 10, R3/R10.4). Отсутствие -- не работа,
        # само по себе per-day переработку не даёт (полнодневное отсутствие 8ч у
        # 0.5-ставки давало ложную "+4"). Но рабочие спец-категории того же дня
        # (КП/ОПВ/Обучение) и проекты ОСТАЮТСЯ в hours_by_day -> частичный день
        # (4ч отпуск + 6ч работа у 0.5) сохраняет легитимную переработку по
        # рабочей части. Отбор absence через normalize_for_classification (C3).
        for category in timesheet.special_categories:
            cat_name = category.category
            if cat_name and normalize_for_classification(cat_name).lower() in _ABSENCE_CLASSIFY:
                continue  # absence-категория не даёт per-day переработку
            for day, hours in category.daily_hours.items():
                if day <= check_until_day:
                    hours_by_day[day] = hours_by_day.get(day, 0.0) + hours

        # Проверяем каждый день
        overtime_days = []  # (день, часов, тип_дня, норма)

        # Календарь сетевой: is_holiday/is_shortened_day бросают RuntimeError при
        # недоступности. Проверка переработок (warning-уровень) не должна ронять
        # всю валидацию - при недоступном календаре пропускаем детекцию
        # переработок, валидация продолжается, отчёт строится (F-07).
        try:
            for day, hours in sorted(hours_by_day.items()):
                if hours <= 0:
                    continue

                check_date = date(year, month, day)

                if self.calendar_manager.is_holiday(check_date):
                    # Выходной/праздник - любые часы = переработка
                    overtime_days.append((day, hours, "выходной", 0))
                elif self.calendar_manager.is_shortened_day(check_date):
                    # Предпраздничный день - норма 8 * ставка минус полный 1 час
                    # (ст. 95 ТК РФ: сокращение на 1 час, без пропорции ставке)
                    day_norm = max(8 * rate - 1, 0)
                    if hours > day_norm:
                        overtime_days.append((day, hours, "предпраздничный", day_norm))
                else:
                    # Обычный рабочий день - норма 8 * ставка
                    day_norm = 8 * rate
                    if hours > day_norm:
                        overtime_days.append((day, hours, "рабочий", day_norm))
        except RuntimeError as e:
            log_warning(
                f"Fsm_6_1_2: производственный календарь недоступен, проверка "
                f"переработок пропущена для {timesheet.fio}: {e}"
            )
            return result

        # Формируем предупреждения
        for day, hours, day_type, norm in overtime_days[:10]:  # Ограничиваем количество
            if day_type == "выходной":
                result.add_warning(
                    f"Переработка {day:02d}.{month:02d}: {hours} ч. ({day_type})"
                )
            else:
                overtime_hours = hours - norm
                result.add_warning(
                    f"Переработка {day:02d}.{month:02d}: {hours} ч. (+{overtime_hours} ч., {day_type})"
                )

        if len(overtime_days) > 10:
            result.add_warning(
                f"... и ещё {len(overtime_days) - 10} дней с переработкой"
            )

        return result

    def validate_absence_placement(self, timesheet: TimesheetData) -> ValidationResult:
        """
        Валидация размещения отсутствий (fail-closed, ревизия 10 / R10.6c).

        Отбраковывает табель с аномальным заполнением absence-категорий
        (отпуск/больничный/отгул). Причина -- отгул выкупает норму через факт:
        аномальное заполнение (отгул на выходной / двойное absence / absence >
        полного дня) даёт ФАНТОМНУЮ переработку в месячном отклонении. Защита
        конструкцией (пока-ёкэ): аномалия -> add_error -> is_valid=False ->
        исключение табеля из расчёта с причиной в отчёт-окно.

        Правила для КАЖДОГО дня d:
        1. absence-часы > 0 на НЕРАБОЧЕМ дне (not is_workday) -> ошибка.
           Регламент: не ставить 8ки на выходные.
        2. >1 absence-КАТЕГОРИИ с часами > 0 в день d -> ошибка (несовместимо:
           нельзя одновременно отпуск/больничный/отгул).
        3. Σ absence-часов дня d > 8 (ФИКСИРОВАННЫЙ полный день, НЕ day_norm,
           НЕ предпраздничные 7, НЕ масштаб ставкой) -> ошибка. Покрывает двойное
           absence (16>8) и absence>8ч/день. КРИТИЧНО (R10.6c п.3): порог = 8, НЕ
           норма дня -- иначе ложно бракует легитимный отпуск@8 на предпраздничном
           (кейс G: excused=min(8,7)=7 в норме, но ЗАПОЛНЕНИЕ 8ч мандатировано
           регламентом). "Сколько absence зачитывается в норму" (cap day_norm=7,
           это compute_employee_norm) != "какое заполнение аномально" (>8, это
           здесь) -- РАЗНЫЕ пороги.

        Отбор absence -- ABSENCE (все три) через normalize_for_classification (C3).

        RuntimeError календаря (F-07 graceful, как validate_overtime/workdays):
        п.1 (is_workday) требует сетевой календарь. При недоступности -> ловим
        RuntimeError и возвращаем текущий result (проверка размещения пропущена,
        валидация продолжается, НЕ краш). п.2 (>1 категории) и п.3 (Σ>8) -- чистая
        арифметика без календаря -- считаются ДО обращения к is_workday, поэтому
        при недоступном календаре они уже выполнены.

        Args:
            timesheet: Данные табеля

        Returns:
            Результат валидации (ошибки на аномальных днях)
        """
        result = ValidationResult(is_valid=True)

        if timesheet.month_start is None:
            return result

        year = timesheet.year
        month = timesheet.month
        check_until_day = self.get_end_day(year, month)

        # Собираем per-day: {день: {нормализованная_absence_категория: Σ часов}}.
        # Только absence-категории (ABSENCE через normalize_for_classification).
        absence_by_day_cat: Dict[int, Dict[str, float]] = {}
        for category in timesheet.special_categories:
            cat_name = category.category
            if not cat_name:
                continue
            norm_name = normalize_for_classification(cat_name).lower()
            if norm_name not in _ABSENCE_CLASSIFY:
                continue
            for day, hours in category.daily_hours.items():
                if day > check_until_day or hours <= 0:
                    continue
                per_cat = absence_by_day_cat.setdefault(day, {})
                per_cat[norm_name] = per_cat.get(norm_name, 0.0) + hours

        # Правила п.2 (>1 категории) и п.3 (Σ > 8) -- БЕЗ календаря, считаем сразу.
        # RuntimeError-безопасны: не обращаются к сетевому is_workday.
        for day in sorted(absence_by_day_cat.keys()):
            per_cat = absence_by_day_cat[day]
            # п.2: несовместимые отсутствия в один день
            if len(per_cat) > 1:
                cats_str = ", ".join(sorted(per_cat.keys()))
                result.add_error(
                    f"Несовместимые отсутствия в один день "
                    f"{day:02d}.{month:02d}: {cats_str} "
                    f"(нельзя одновременно отпуск/больничный/отгул)"
                )
            # п.3: суммарные absence-часы дня > полного дня (фикс. 8)
            day_absence_sum = sum(per_cat.values())
            if day_absence_sum > 8:
                result.add_error(
                    f"Отсутствие превышает полный день "
                    f"{day:02d}.{month:02d}: {day_absence_sum} ч (> 8 ч)"
                )

        # Правило п.1 (absence на нерабочий день) -- ТРЕБУЕТ сетевой календарь.
        # F-07 graceful: недоступен -> пропускаем п.1 (п.2/п.3 уже выполнены),
        # валидация продолжается, не краш (как validate_workdays/validate_overtime).
        try:
            for day in sorted(absence_by_day_cat.keys()):
                check_date = date(year, month, day)
                if not self.calendar_manager.is_workday(check_date):
                    result.add_error(
                        f"Отсутствие проставлено на нерабочий день "
                        f"{day:02d}.{month:02d}"
                    )
        except RuntimeError as e:
            log_warning(
                f"Fsm_6_1_2: производственный календарь недоступен, проверка "
                f"размещения отсутствий (нерабочий день) пропущена для "
                f"{timesheet.fio}: {e}"
            )
            return result

        return result

    def validate_total_consistency(self, timesheet: TimesheetData) -> ValidationResult:
        """
        Валидация согласованности итоговой ячейки часов с суммой подённых.

        Доменный инвариант валидного табеля: итог часов (total_hours) равен
        сумме ВСЕХ подённых ячеек (Σ по projects.daily_hours +
        Σ по special_categories.daily_hours). В корректном табеле все ячейки
        заполнены цифрами (кроме праздников/выходных), поэтому total == Σdaily.

        Расхождение total != Σdaily означает невалидный вход (итоговая ячейка
        содержит формулу/ручную правку без подённой детализации, либо
        подённые ячейки неполны). При таком входе расчёт нормы через
        подённый источник absence неверен -> fail-closed: помечаем нарушение
        валидности, расчёт нормы не выполняется (закрывает класс дефекта
        "total без daily" по построению).

        Допуск 0.5 часа поглощает округления.

        Args:
            timesheet: Данные табеля

        Returns:
            Результат валидации
        """
        result = ValidationResult(is_valid=True)

        # Допуск на округления (часы)
        TOLERANCE = 0.5

        # Σ всех подённых часов: проекты + специальные категории
        sum_daily = 0.0
        for project in timesheet.projects:
            sum_daily += sum(project.daily_hours.values())
        for category in timesheet.special_categories:
            sum_daily += sum(category.daily_hours.values())

        deviation = abs(timesheet.total_hours - sum_daily)

        if deviation > TOLERANCE:
            result.add_error(
                f"Итог часов не сходится с суммой подённых: "
                f"итог={timesheet.total_hours}, Σподённых={sum_daily}, "
                f"расхождение={round(deviation, 2)} ч (допуск {TOLERANCE} ч)"
            )
            log_warning(
                f"Fsm_6_1_2: рассинхрон total/daily для {timesheet.fio}: "
                f"total={timesheet.total_hours}, Σdaily={sum_daily}, "
                f"расхождение={round(deviation, 2)} ч"
            )

        return result

    def validate(self, timesheet: TimesheetData) -> ValidationResult:
        """
        Полная валидация табеля.

        Args:
            timesheet: Данные табеля

        Returns:
            Результат валидации со всеми ошибками и предупреждениями
        """
        result = ValidationResult(is_valid=True)

        log_info(f"Fsm_6_1_2: Валидация файла {timesheet.filename}")

        # Валидация имени файла
        filename_result = self.validate_filename(timesheet.filename)
        result.merge(filename_result)

        # Если имя файла невалидно - дальше не проверяем
        if not filename_result.is_valid:
            return result

        # Валидация ФИО
        fio_result = self.validate_fio(timesheet)
        result.merge(fio_result)

        # Валидация месяца
        month_result = self.validate_month(timesheet)
        result.merge(month_result)

        # Валидация шифров проектов
        codes_result = self.validate_project_codes(timesheet)
        result.merge(codes_result)

        # Валидация согласованности итога с суммой подённых (fail-closed):
        # рассинхрон total/daily -> ошибка валидности. Применяется КО ВСЕМ,
        # включая руководителя: его табель парсится тем же parse_timesheet ->
        # daily_hours заполняется идентично (отличие табеля руководителя --
        # только расположение файла). Валидный табель имеет total == Σdaily,
        # malformed (формула/ручной итог без подённого) -> отвергается.
        consistency_result = self.validate_total_consistency(timesheet)
        result.merge(consistency_result)

        # Гейт отбраковки (FIX-6, вариант б / OPT-005 / OPT-019): если табель
        # уже невалиден (месяц-mismatch, битый B4, unknown-шифр, рассинхрон
        # total/daily) -> НЕ выполнять validate_workdays/validate_overtime.
        # Эти проверки на отбракованном табеле добавили бы warning-шум
        # ("рабочий день не заполнен" по GUI-календарю на файле, который и так
        # выкинут) -> вводят заказчика в заблуждение. Blast-radius (подавление
        # вторичных warnings для ВСЕХ невалидных, не только месяц) осознан.
        # ValueError-краша тут НЕТ: validate_workdays -> get_workdays_until_date
        # без date(); date() только в validate_overtime, уже гейтится ниже.
        if not result.is_valid:
            log_warning(
                f"Fsm_6_1_2: Файл {timesheet.filename} отбракован "
                f"({result.errors_count} ошибок), проверки заполненности/"
                f"переработок пропущены"
            )
            return result

        # Валидация размещения отсутствий (fail-closed, ревизия 10 / R10.6c):
        # аномальное заполнение absence (отгул на выходной / двойное absence /
        # Σ absence > 8) -> отбраковка табеля с причиной. Стоит ПОСЛЕ гейта выше
        # (не тянуть на уже-отбракованные по fio/месяцу/consistency) и ПЕРЕД
        # validate_workdays, со своим гейтом после -- отбракованный аномалией
        # табель не должен плодить вторичные warnings заполненности/переработок.
        absence_placement_result = self.validate_absence_placement(timesheet)
        result.merge(absence_placement_result)

        if not result.is_valid:
            log_warning(
                f"Fsm_6_1_2: Файл {timesheet.filename} отбракован по размещению "
                f"отсутствий ({result.errors_count} ошибок), проверки "
                f"заполненности/переработок пропущены"
            )
            return result

        # Валидация заполненности рабочих дней и переработок. Применяется
        # КО ВСЕМ, включая руководителя: его табель структурно идентичен
        # (тот же parse_timesheet, daily_hours заполнен) -- проверки работают
        # на полях TimesheetData, не на расположении файла.
        workdays_result = self.validate_workdays(timesheet)
        result.merge(workdays_result)

        # Валидация переработок (только для валидных табелей)
        if result.is_valid:
            overtime_result = self.validate_overtime(timesheet)
            result.merge(overtime_result)

        # Итоговая информация
        if result.is_valid:
            log_info(f"Fsm_6_1_2: Файл {timesheet.filename} прошел валидацию")
        else:
            log_warning(
                f"Fsm_6_1_2: Файл {timesheet.filename} не прошел валидацию "
                f"({result.errors_count} ошибок)"
            )

        return result

    def get_missing_employees(
        self,
        timesheets: List[TimesheetData]
    ) -> List[dict]:
        """
        Найти сотрудников из базы, для которых нет табеля.

        Args:
            timesheets: Список загруженных табелей

        Returns:
            Список сотрудников без табелей
        """
        employees = self._get_employees()

        # Собираем фамилии из загруженных табелей (из имени файла)
        loaded_surnames = set()
        for ts in timesheets:
            match = self.FILENAME_PATTERN.match(ts.filename)
            if match:
                loaded_surnames.add(match.group(1).lower())

        # Находим сотрудников без табелей
        missing = []
        for emp in employees:
            surname = emp.get('last_name', '').lower()
            if surname and surname not in loaded_surnames:
                missing.append(emp)

        return missing

    def validate_all(self, timesheets: List[TimesheetData]) -> List[Tuple[TimesheetData, ValidationResult]]:
        """
        Валидация списка табелей.

        Также проверяет наличие табелей для всех сотрудников из базы.

        Args:
            timesheets: Список данных табелей

        Returns:
            Список кортежей (табель, результат_валидации).
            Для отсутствующих сотрудников создаётся "виртуальный" результат с ошибкой.
        """
        results = []

        # Валидация загруженных табелей
        for timesheet in timesheets:
            validation_result = self.validate(timesheet)
            results.append((timesheet, validation_result))

        # Проверка отсутствующих табелей
        missing_employees = self.get_missing_employees(timesheets)
        for emp in missing_employees:
            full_name = self.employee_manager.get_employee_full_name(emp, format='full')
            surname = emp.get('last_name', '')

            # Создаём "виртуальный" результат для отсутствующего табеля
            missing_result = ValidationResult(is_valid=False)
            missing_result.add_error(f"Табель не найден для сотрудника: {full_name}")

            # Создаём минимальный TimesheetData для отображения в отчёте
            missing_timesheet = TimesheetData(
                filepath="",
                filename=f"{surname}_{self._target_month:02d}.xlsx (отсутствует)",
                fio=full_name,
                month_start=None,
                month_end=None,
                year=0,
                month=self._target_month
            )
            results.append((missing_timesheet, missing_result))

        # Статистика
        valid_count = sum(1 for _, r in results if r.is_valid)
        total_count = len(results)

        log_info(
            f"Fsm_6_1_2: Валидация завершена: {valid_count} из {total_count} "
            f"табелей прошли валидацию"
        )

        if missing_employees:
            log_warning(
                f"Fsm_6_1_2: Не найдены табели для {len(missing_employees)} сотрудников"
            )

        return results

    def get_valid_timesheets(
        self,
        validation_results: List[Tuple[TimesheetData, ValidationResult]]
    ) -> List[TimesheetData]:
        """
        Получить только валидные табели.

        Args:
            validation_results: Результаты валидации

        Returns:
            Список валидных табелей
        """
        return [ts for ts, result in validation_results if result.is_valid]


def format_validation_report(
    validation_results: List[Tuple[TimesheetData, ValidationResult]],
    target_year: int,
    target_month: int,
    use_html: bool = True,
    end_day: Optional[int] = None,
    employee_rates: Optional[Dict[str, float]] = None,
    calendar_manager: Optional[ProductionCalendarManager] = None,
    calendar_unavailable: bool = False
) -> str:
    """
    Форматировать отчет валидации для GUI.

    Показывает детально только проблемные табели (ошибки, предупреждения, отклонения).
    Полностью валидные табели без замечаний сворачиваются в одну строку.

    Args:
        validation_results: Результаты валидации
        target_year: Год периода (из GUI, authoritative для расчёта нормы).
        target_month: Месяц периода (из GUI, authoritative для расчёта нормы).
        use_html: Использовать HTML форматирование (красный цвет для ошибок)
        end_day: Последний день для расчёта часов (включительно).
                 Если None - суммируются все подённые часы (Σdaily, D4).
        employee_rates: Словарь {ФИО: ставка} для расчёта индивидуальной нормы.
                       Если None - используется ставка 1.0.
        calendar_manager: ProductionCalendarManager (источник статуса дня). Если None
                          или calendar_unavailable - норма/отклонение не рассчитываются.
        calendar_unavailable: флаг недоступности календаря.

    Returns:
        Текстовый или HTML отчет
    """
    lines = ["=== Валидация табелей ===", ""]

    # HTML цвета
    RED = '<span style="color: #cc0000;">'
    YELLOW = '<span style="color: #cc9900;">'
    END = '</span>'

    def get_hours(ts: TimesheetData) -> float:
        """Получить ФАКТ часов из Σdaily (D4/R5-2), симметрично summary.

        summary считает employee_total как Σ подённых ячеек. Validator-отчёт
        обязан использовать ТУ ЖЕ формулу факта, а не ts.total_hours (COL_TOTAL):
        при total_hours != Σdaily в допуске 0.5 ч иначе получилось бы разное
        "Отклонение" одному сотруднику в отчёте и в файле. При end_day is None
        суммируем все дни месяца (реальное число дней target_year/target_month,
        а не хрупкий литерал 31 -- симметрично "все дни").
        """
        if end_day is not None:
            return ts.get_hours_until_day(end_day)
        import calendar
        last_day = calendar.monthrange(target_year, target_month)[1]
        return ts.get_hours_until_day(last_day)

    def get_employee_norm(ts: TimesheetData) -> Optional[float]:
        """Получить индивидуальную норму часов сотрудника через единый helper.

        Норма считается по производственному календарю (рабочие дни с учётом
        предпраздничного сокращения). Отпуск/больничный (NEUTRALIZING)
        нейтрализуются подённо с cap; отгул (BUYOUT, ревизия 10) выкупает норму
        (ст. 128) -- остаётся в факте, из нормы полностью вычитается. При
        недоступности календаря -> None (отклонение пустое).
        """
        if calendar_manager is None or calendar_unavailable:
            return None
        rate = 1.0
        if employee_rates and ts.fio in employee_rates:
            rate = employee_rates[ts.fio]
        # per-day карта часов отсутствия (C2/FIX-2), согласованный с фактом
        # отбор absence через normalize_for_classification (C3/R5-1).
        absence_map = absence_by_day(ts, end_day)
        return compute_employee_norm(
            ts, absence_map, rate, end_day,
            calendar_manager, target_year, target_month,
            calendar_unavailable
        )

    # Разделяем на проблемные и полностью OK
    perfect_timesheets = []  # Валидные без замечаний и без отклонения
    problem_timesheets = []  # С ошибками, предупреждениями или отклонением

    for timesheet, result in validation_results:
        hours = get_hours(timesheet)
        emp_norm = get_employee_norm(timesheet)

        if not result.is_valid:
            # Невалидный - проблемный
            problem_timesheets.append((timesheet, result))
        elif result.messages:
            # Валидный но есть сообщения (предупреждения) - проблемный
            problem_timesheets.append((timesheet, result))
        elif emp_norm is not None and emp_norm > 0:
            # Проверяем отклонение от индивидуальной нормы (float-шум через round)
            deviation = hours - emp_norm
            if round(deviation, 2) != 0:
                # Есть отклонение - проблемный
                problem_timesheets.append((timesheet, result))
            else:
                # Полностью OK
                perfect_timesheets.append((timesheet, result))
        else:
            # Норма не задана/недоступна, валидный без сообщений - OK
            perfect_timesheets.append((timesheet, result))

    # Выводим проблемные табели детально
    for timesheet, result in problem_timesheets:
        hours = get_hours(timesheet)
        emp_norm = get_employee_norm(timesheet)

        if result.is_valid:
            status_line = f"[OK] {timesheet.filename}"
        else:
            if use_html:
                status_line = f'{RED}[ERROR] {timesheet.filename}{END}'
            else:
                status_line = f"[ERROR] {timesheet.filename}"
        lines.append(status_line)

        for msg in result.messages:
            row_info = f" (строка {msg.row})" if msg.row else ""

            if msg.level == "ERROR":
                if use_html:
                    lines.append(f'{RED}  - {msg.message}{row_info}{END}')
                else:
                    lines.append(f"  - {msg.message}{row_info}")
            elif msg.level == "WARNING":
                # Переработки выделяем оранжевым (YELLOW), остальные предупреждения - красным
                is_overtime = "Переработка" in msg.message
                if use_html:
                    color = YELLOW if is_overtime else RED
                    lines.append(f'{color}  ! {msg.message}{row_info}{END}')
                else:
                    lines.append(f"  ! {msg.message}{row_info}")
            else:
                lines.append(f"  {msg.message}{row_info}")

        # Добавляем информацию о сотруднике для валидных табелей
        if result.is_valid and timesheet.fio:
            lines.append(f"  Сотрудник: {timesheet.fio}")
            lines.append(f"  Проектов: {len(timesheet.projects)}")

            # Часы с отклонением от индивидуальной нормы
            hours_str = f"{hours}"
            if emp_norm is not None and emp_norm > 0:
                deviation = hours - emp_norm
                if round(deviation, 2) != 0:
                    deviation_disp = round(deviation, 2)
                    if use_html:
                        hours_str = f"{hours} {YELLOW}({deviation_disp}){END}"
                    else:
                        hours_str = f"{hours} ({deviation_disp})"
            lines.append(f"  Часов: {hours_str}")

        lines.append("")

    # Выводим полностью OK одной строкой
    if perfect_timesheets:
        lines.append(f"[OK] {len(perfect_timesheets)} табелей без замечаний")
        lines.append("")

    # Итого
    valid_count = len(perfect_timesheets) + sum(1 for _, r in problem_timesheets if r.is_valid)
    total_count = len(validation_results)
    lines.append(f"Итого: {valid_count} из {total_count} табелей прошли валидацию")

    if use_html:
        # Преобразуем переносы строк в HTML
        return "<br>".join(lines)
    return "\n".join(lines)
