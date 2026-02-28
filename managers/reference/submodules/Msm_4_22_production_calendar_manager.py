# -*- coding: utf-8 -*-
"""
Менеджер производственного календаря РФ.

Загружает данные с xmlcalendar.ru API с кэшированием в памяти.
Используется для валидации заполненности рабочих дней в табелях (F_6_1).

API: https://xmlcalendar.ru/data/ru/{year}/calendar.json
"""

import calendar
import threading
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Set
from Daman_QGIS.utils import log_info, log_warning, log_error


class ProductionCalendarManager:
    """Менеджер для работы с производственным календарем РФ."""

    API_URL_TEMPLATE = "https://xmlcalendar.ru/data/ru/{year}/calendar.json"

    # Lock для thread-safe доступа к кэшам
    _lock = threading.Lock()

    # Кэш календарей по годам (на время сессии)
    _calendar_cache: Dict[int, Dict] = {}

    # Кэш выходных дней по годам {year: {(month, day), ...}}
    _holidays_cache: Dict[int, Set[tuple]] = {}

    # Кэш сокращенных дней по годам {year: {(month, day), ...}}
    _shortened_cache: Dict[int, Set[tuple]] = {}

    def get_calendar(self, year: int) -> Optional[Dict]:
        """
        Получить производственный календарь на год.

        Thread-safe: использует double-checked locking для минимизации
        блокировок при частых обращениях к кэшу.

        Args:
            year: Год (например, 2026)

        Returns:
            Словарь с данными календаря или None при ошибке
        """
        # Fast path - проверяем кэш без блокировки
        if year in ProductionCalendarManager._calendar_cache:
            return ProductionCalendarManager._calendar_cache[year]

        # Slow path - блокировка для загрузки
        with ProductionCalendarManager._lock:
            # Double-check после получения блокировки
            if year in ProductionCalendarManager._calendar_cache:
                return ProductionCalendarManager._calendar_cache[year]

            # Загружаем с API
            calendar_data = self._load_from_api(year)

            if calendar_data:
                ProductionCalendarManager._calendar_cache[year] = calendar_data
                self._parse_calendar(year, calendar_data)

            return calendar_data

    def _load_from_api(self, year: int) -> Optional[Dict]:
        """
        Загрузить календарь с xmlcalendar.ru API.

        Args:
            year: Год

        Returns:
            Данные календаря или None при ошибке
        """
        try:
            import requests
        except ImportError:
            log_warning("Msm_4_22: requests не установлен")
            return self._get_fallback_calendar(year)

        url = self.API_URL_TEMPLATE.format(year=year)

        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                log_info(f"Msm_4_22: Загружен календарь на {year} год")
                return data
            else:
                log_warning(f"Msm_4_22: HTTP {response.status_code} для календаря {year}")
        except requests.exceptions.Timeout:
            log_warning(f"Msm_4_22: Таймаут при загрузке календаря {year}")
        except requests.exceptions.RequestException as e:
            log_warning(f"Msm_4_22: Ошибка сети при загрузке календаря {year}: {e}")
        except Exception as e:
            log_error(f"Msm_4_22: Ошибка парсинга календаря {year}: {e}")

        # Возвращаем fallback календарь
        return self._get_fallback_calendar(year)

    def _get_fallback_calendar(self, year: int) -> Optional[Dict]:
        """
        Получить fallback календарь (выходные = суббота, воскресенье).

        Args:
            year: Год

        Returns:
            Базовый календарь с выходными по субботам и воскресеньям
        """
        log_warning(f"Msm_4_22: Используется fallback календарь для {year}")

        months_data = []
        for month in range(1, 13):
            # Находим все субботы (5) и воскресенья (6) в месяце
            weekends = []
            _, num_days = calendar.monthrange(year, month)
            for day in range(1, num_days + 1):
                weekday = calendar.weekday(year, month, day)
                if weekday in (5, 6):  # Суббота или воскресенье
                    weekends.append(str(day))

            months_data.append({
                "month": month,
                "days": ",".join(weekends)
            })

        return {
            "year": year,
            "months": months_data,
            "statistic": {
                "workdays": 0,  # Будет пересчитано
                "holidays": 0
            }
        }

    def _parse_calendar(self, year: int, calendar_data: Dict) -> None:
        """
        Распарсить календарь и заполнить кэши выходных и сокращенных дней.

        Args:
            year: Год
            calendar_data: Данные календаря
        """
        holidays: Set[tuple] = set()
        shortened: Set[tuple] = set()

        months = calendar_data.get('months', [])
        for month_data in months:
            month = month_data.get('month', 0)
            days_str = month_data.get('days', '')

            if not days_str:
                continue

            # Формат JSON xmlcalendar.ru: "1,2,3,4,5,6,7,8,9+,10,11,17,18,24,25,31"
            # Все числа в days - это НЕРАБОЧИЕ дни (выходные/праздники)
            # + = выходной, перенесённый С другого дня (всё равно выходной!)
            # * = сокращённый предпраздничный день (рабочий, НЕ выходной)
            for day_part in days_str.split(','):
                day_part = day_part.strip()
                if not day_part:
                    continue

                if day_part.endswith('*'):
                    # Сокращённый предпраздничный день - это РАБОЧИЙ день
                    # НЕ добавляем в holidays
                    day = int(day_part[:-1])
                    shortened.add((month, day))
                elif day_part.endswith('+'):
                    # Выходной день, перенесённый с другого дня
                    # Это всё равно ВЫХОДНОЙ, добавляем в holidays
                    day = int(day_part[:-1])
                    holidays.add((month, day))
                else:
                    # Обычный выходной/праздник
                    try:
                        day = int(day_part)
                        holidays.add((month, day))
                    except ValueError:
                        pass

        ProductionCalendarManager._holidays_cache[year] = holidays
        ProductionCalendarManager._shortened_cache[year] = shortened

    def is_workday(self, check_date: date) -> bool:
        """
        Проверить, является ли дата рабочим днем.

        Args:
            check_date: Дата для проверки

        Returns:
            True если рабочий день
        """
        year = check_date.year
        month = check_date.month
        day = check_date.day

        # Загружаем календарь если нужно
        if year not in ProductionCalendarManager._holidays_cache:
            self.get_calendar(year)

        holidays = ProductionCalendarManager._holidays_cache.get(year, set())
        return (month, day) not in holidays

    def is_holiday(self, check_date: date) -> bool:
        """
        Проверить, является ли дата выходным/праздником.

        Args:
            check_date: Дата для проверки

        Returns:
            True если выходной или праздник
        """
        return not self.is_workday(check_date)

    def is_shortened_day(self, check_date: date) -> bool:
        """
        Проверить, является ли дата сокращенным (предпраздничным) днем.

        Args:
            check_date: Дата для проверки

        Returns:
            True если сокращенный день
        """
        year = check_date.year
        month = check_date.month
        day = check_date.day

        # Загружаем календарь если нужно
        if year not in ProductionCalendarManager._shortened_cache:
            self.get_calendar(year)

        shortened = ProductionCalendarManager._shortened_cache.get(year, set())
        return (month, day) in shortened

    def get_workdays_in_month(self, year: int, month: int) -> List[int]:
        """
        Получить список рабочих дней в месяце.

        Args:
            year: Год
            month: Месяц (1-12)

        Returns:
            Список номеров рабочих дней
        """
        # Загружаем календарь если нужно
        if year not in ProductionCalendarManager._holidays_cache:
            self.get_calendar(year)

        holidays = ProductionCalendarManager._holidays_cache.get(year, set())

        _, num_days = calendar.monthrange(year, month)
        workdays = []

        for day in range(1, num_days + 1):
            if (month, day) not in holidays:
                workdays.append(day)

        return workdays

    def get_workdays_until_date(self, year: int, month: int, until_day: int) -> List[int]:
        """
        Получить список рабочих дней в месяце до указанной даты (не включая).

        Args:
            year: Год
            month: Месяц (1-12)
            until_day: День до которого получить рабочие дни (не включая)

        Returns:
            Список номеров рабочих дней
        """
        all_workdays = self.get_workdays_in_month(year, month)
        return [d for d in all_workdays if d < until_day]

    def get_workdays_count(self, year: int, month: int) -> int:
        """
        Получить количество рабочих дней в месяце.

        Args:
            year: Год
            month: Месяц (1-12)

        Returns:
            Количество рабочих дней
        """
        return len(self.get_workdays_in_month(year, month))

    def get_work_hours_for_period(
        self,
        start_date: date,
        end_date: date,
        hours_per_day: int = 8
    ) -> float:
        """
        Рассчитать норму рабочих часов за период с учётом предпраздничных дней.

        Предпраздничные дни имеют на 1 час меньше (7 часов вместо 8).

        Args:
            start_date: Начало периода (включительно)
            end_date: Конец периода (включительно)
            hours_per_day: Базовое количество часов в рабочем дне (по умолчанию 8)

        Returns:
            Общее количество рабочих часов за период
        """
        total_hours = 0.0
        current = start_date

        while current <= end_date:
            if self.is_workday(current):
                if self.is_shortened_day(current):
                    # Предпраздничный день - на 1 час меньше
                    total_hours += hours_per_day - 1
                else:
                    total_hours += hours_per_day
            current += timedelta(days=1)

        return total_hours

    def get_work_hours_for_month(self, year: int, month: int, hours_per_day: int = 8) -> float:
        """
        Рассчитать норму рабочих часов за весь месяц с учётом предпраздничных дней.

        Args:
            year: Год
            month: Месяц (1-12)
            hours_per_day: Базовое количество часов в рабочем дне (по умолчанию 8)

        Returns:
            Общее количество рабочих часов за месяц
        """
        _, num_days = calendar.monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, num_days)
        return self.get_work_hours_for_period(start_date, end_date, hours_per_day)

    @classmethod
    def clear_cache(cls):
        """Очистить весь кэш календарей."""
        cls._calendar_cache.clear()
        cls._holidays_cache.clear()
        cls._shortened_cache.clear()

    @classmethod
    def reload(cls, year: Optional[int] = None):
        """
        Перезагрузить календарь.

        Args:
            year: Год для перезагрузки. Если None, очищается весь кэш.
        """
        if year:
            cls._calendar_cache.pop(year, None)
            cls._holidays_cache.pop(year, None)
            cls._shortened_cache.pop(year, None)
        else:
            cls.clear_cache()
