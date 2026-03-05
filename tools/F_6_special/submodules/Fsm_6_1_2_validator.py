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
from datetime import datetime, date
from typing import Dict, List, Optional, Set, Tuple

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers.reference import EmployeeReferenceManager
from Daman_QGIS.managers.reference.submodules import ProductionCalendarManager
from .Fsm_6_1_3_parser import TimesheetData, SPECIAL_CATEGORIES, load_valid_project_codes


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

    def __init__(self, target_month: Optional[int] = None, end_day: Optional[int] = None):
        """
        Инициализация валидатора.

        Args:
            target_month: Целевой месяц (1-12). Если None - текущий месяц.
            end_day: Последний день для расчётов (включительно).
                     Если None - последний день месяца.
        """
        self._target_month = target_month if target_month is not None else datetime.now().month
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
        Валидация месяца табеля.

        Args:
            timesheet: Данные табеля

        Returns:
            Результат валидации
        """
        result = ValidationResult(is_valid=True)

        if timesheet.month_start is None:
            result.add_warning("Не удалось определить месяц из ячейки B4")
            return result

        target_month = self.get_target_month()

        if not self.is_valid_month(timesheet.month):
            result.add_warning(
                f"Указан месяц {timesheet.month}, ожидается {target_month}"
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

        # Получаем рабочие дни для проверки (до end_day включительно)
        workdays = self.calendar_manager.get_workdays_until_date(
            year, month, check_until_day + 1
        )

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
        - Предпраздничные дни: >7*ставка часов
        - Выходные/праздники: любые часы (>0)

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

        # Собираем часы по дням
        hours_by_day: Dict[int, float] = {}
        for project in timesheet.projects:
            for day, hours in project.daily_hours.items():
                if day <= check_until_day:
                    hours_by_day[day] = hours_by_day.get(day, 0.0) + hours

        for category in timesheet.special_categories:
            for day, hours in category.daily_hours.items():
                if day <= check_until_day:
                    hours_by_day[day] = hours_by_day.get(day, 0.0) + hours

        # Проверяем каждый день
        overtime_days = []  # (день, часов, тип_дня, норма)

        for day, hours in sorted(hours_by_day.items()):
            if hours <= 0:
                continue

            check_date = date(year, month, day)

            if self.calendar_manager.is_holiday(check_date):
                # Выходной/праздник - любые часы = переработка
                overtime_days.append((day, hours, "выходной", 0))
            elif self.calendar_manager.is_shortened_day(check_date):
                # Предпраздничный день - норма 7 * ставка
                day_norm = 7 * rate
                if hours > day_norm:
                    overtime_days.append((day, hours, "предпраздничный", day_norm))
            else:
                # Обычный рабочий день - норма 8 * ставка
                day_norm = 8 * rate
                if hours > day_norm:
                    overtime_days.append((day, hours, "рабочий", day_norm))

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

        # Валидация заполненности рабочих дней
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
    use_html: bool = True,
    norm_hours: Optional[float] = None,
    end_day: Optional[int] = None,
    employee_rates: Optional[Dict[str, float]] = None
) -> str:
    """
    Форматировать отчет валидации для GUI.

    Показывает детально только проблемные табели (ошибки, предупреждения, отклонения).
    Полностью валидные табели без замечаний сворачиваются в одну строку.

    Args:
        validation_results: Результаты валидации
        use_html: Использовать HTML форматирование (красный цвет для ошибок)
        norm_hours: Базовая норма часов за период (для полной ставки)
        end_day: Последний день для расчёта часов (включительно).
                 Если None - используется total_hours из табеля (все дни).
        employee_rates: Словарь {ФИО: ставка} для расчёта индивидуальной нормы.
                       Если None - используется норма для полной ставки.

    Returns:
        Текстовый или HTML отчет
    """
    lines = ["=== Валидация табелей ===", ""]

    # HTML цвета
    RED = '<span style="color: #cc0000;">'
    YELLOW = '<span style="color: #cc9900;">'
    END = '</span>'

    def get_hours(ts: TimesheetData) -> float:
        """Получить часы с учётом end_day."""
        if end_day is not None:
            return ts.get_hours_until_day(end_day)
        return ts.total_hours

    def get_vacation_hours(ts: TimesheetData) -> float:
        """Получить часы отпуска с учётом end_day."""
        if end_day is not None:
            return ts.get_vacation_hours_until_day(end_day)
        return ts.vacation_hours

    def get_employee_norm(fio: str, vacation_hours: float) -> float:
        """Получить норму часов для сотрудника с учётом ставки.

        Отпуск считается по полной ставке (1.0), остальное -- по ставке сотрудника.
        Формула: (norm - vacation) * rate + vacation
        """
        if norm_hours is None or norm_hours <= 0:
            return 0.0
        rate = 1.0
        if employee_rates and fio in employee_rates:
            rate = employee_rates[fio]
        if rate == 1.0:
            return norm_hours
        # Отпуск по полной ставке, рабочие дни по ставке сотрудника
        work_norm = norm_hours - vacation_hours
        return work_norm * rate + vacation_hours

    # Разделяем на проблемные и полностью OK
    perfect_timesheets = []  # Валидные без замечаний и без отклонения
    problem_timesheets = []  # С ошибками, предупреждениями или отклонением

    for timesheet, result in validation_results:
        hours = get_hours(timesheet)
        vacation = get_vacation_hours(timesheet)
        emp_norm = get_employee_norm(timesheet.fio, vacation)

        if not result.is_valid:
            # Невалидный - проблемный
            problem_timesheets.append((timesheet, result))
        elif result.messages:
            # Валидный но есть сообщения (предупреждения) - проблемный
            problem_timesheets.append((timesheet, result))
        elif emp_norm > 0:
            # Проверяем отклонение от индивидуальной нормы
            deviation = hours - emp_norm
            if deviation != 0:
                # Есть отклонение - проблемный
                problem_timesheets.append((timesheet, result))
            else:
                # Полностью OK
                perfect_timesheets.append((timesheet, result))
        else:
            # Норма не задана, валидный без сообщений - OK
            perfect_timesheets.append((timesheet, result))

    # Выводим проблемные табели детально
    for timesheet, result in problem_timesheets:
        hours = get_hours(timesheet)
        vacation = get_vacation_hours(timesheet)
        emp_norm = get_employee_norm(timesheet.fio, vacation)

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
            if emp_norm > 0:
                deviation = hours - emp_norm
                if deviation != 0:
                    if use_html:
                        hours_str = f"{hours} {YELLOW}({deviation}){END}"
                    else:
                        hours_str = f"{hours} ({deviation})"
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
