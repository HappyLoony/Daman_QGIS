# -*- coding: utf-8 -*-
"""
Fsm_6_1_6: Расчёт индивидуальной нормы часов сотрудника (табель F_6_1).

Общий helper нормы для validator (Fsm_6_1_2) и summary (Fsm_6_1_5): считает
норму из уже отобранной per-day карты отсутствий. Инвариант факт<->норма
(absence-часы сокращаются в deviation) обеспечивают ВЫЗЫВАЮЩИЕ, а не helper --
см. ниже.

Целевая логика (план F_6_1 2026-06-22, ревизия 9 -- по-дневная норма с cap):
- норма строится по РАБОЧИМ дням периода с корректным предпраздничным
  сокращением (полный 1 час после масштабирования ставкой, ст. 95 ТК РФ);
- отсутствия (отпуск/больничный/отгул) нейтрализуются ПО-ДНЕВНО с cap:
  excused(d) = min(absence_on_d, day_norm(d)) -- зачёт не больше дневной нормы,
  work_norm = Σ по рабочим d (day_norm(d) - excused(d)),
  employee_norm = work_norm + absence_total,
  где те же absence-часы входят и в норму, и в факт (employee_total) ->
  сокращаются в deviation. Cap корректен и для полных, и для частичных дней
  отсутствия (устраняет и ложную переработку 0.5-ставки на полном дне, и
  ложную переработку на частичном дне 4ч отпуск + 4ч работа);
- источник часов отсутствия -- absence_by_day (per-day карта из daily_hours
  ABSENCE-категорий). Тождество absence-доли факта и absence_total нормы
  обеспечивается НЕ здесь, а согласованностью вызывающих: сторона факта
  (_build_data_matrix в Fsm_6_1_5) и сторона absence (absence_by_day) применяют
  ОДИН предикат отбора + ОДИН cutoff (d <= end_day) + ОДНУ нормализацию ->
  Σ совпадает by construction. Helper лишь суммирует переданную карту, сам
  инвариант не устанавливает;
- источник year/month -- GUI (authoritative), НЕ ts.year/ts.month (B4);
- при недоступности производственного календаря -> возврат None (graceful
  degradation, пустая ячейка "Отклонение" честнее ложной нормы).
"""

import calendar as _calendar
from datetime import date
from typing import Dict, Optional

from Daman_QGIS.utils import log_warning, normalize_for_classification

# Множество нейтрализуемых категорий-отсутствий (канонический регистр).
# Отбор absence выполняется через normalize_for_classification(x).lower()
# (см. absence_by_day и _build_data_matrix в Fsm_6_1_5): parser хранит
# оригинальный регистр из Excel и невидимые символы, поэтому голый .lower()
# или in-в-ABSENCE промахивается.
ABSENCE = {"Отпуск", "Больничный", "Отгул"}

# Нормализованное+lowercase множество для устойчивого отбора absence.
# Один и тот же предикат применяется на стороне нормы (здесь) и на стороне
# факта (Fsm_6_1_5._build_data_matrix) -> суммы согласованы (R5-1).
_ABSENCE_NORM = {normalize_for_classification(c).lower() for c in ABSENCE}


def absence_by_day(ts, end_day: Optional[int]) -> Dict[int, float]:
    """
    Построить per-day карту часов отсутствия {день: Σ absence-часов}.

    Заменяет прежний build_absence_dict (per-category словарь). Возвращает
    per-day скаляр для cap-формулы compute_employee_norm.

    Согласованность с фактом (R5-1, критично): отбор absence-категорий
    выполняется тем же предикатом, что и на стороне факта
    (_build_data_matrix в Fsm_6_1_5): normalize_for_classification(name).lower()
    in _ABSENCE_NORM. Один предикат + один cutoff (d <= end_day) + одна
    нормализация -> Σ(absence-часов этой карты) тождественна Σ(absence-колонок
    employee_total) на ЛЮБОМ периоде by construction.

    Args:
        ts: TimesheetData.
        end_day: Последний день для расчёта (включительно). None -> все дни.

    Returns:
        Словарь {день: суммарные absence-часы в этом дне} по ABSENCE-категориям.
        Дни без absence-часов отсутствуют.
    """
    result: Dict[int, float] = {}

    for category in ts.special_categories:
        cat_name = category.category
        if not cat_name:
            continue
        if normalize_for_classification(cat_name).lower() not in _ABSENCE_NORM:
            continue
        for d, hours in category.daily_hours.items():
            if end_day is not None and d > end_day:
                continue
            if hours > 0:
                result[d] = result.get(d, 0.0) + hours

    return result


def compute_employee_norm(
    ts,
    absence_by_day_map: Dict[int, float],
    rate: float,
    end_day: Optional[int],
    calendar_manager,
    year: int,
    month: int,
    calendar_unavailable: bool = False,
) -> Optional[float]:
    """
    Рассчитать индивидуальную норму часов сотрудника за период (по-дневная с cap).

    Формула (план F_6_1, §4):
        дни           = range(1, (end_day if end_day else days_in_month) + 1)
        day_norm(d)   = max(8*rate - (1 если предпраздничный(d) иначе 0), 0)
                        (0 если день не рабочий)
        absence_on_d  = absence_by_day_map.get(d, 0.0)
        excused(d)    = min(absence_on_d, day_norm(d))            # cap зачёта
        work_norm     = Σ по рабочим d: (day_norm(d) - excused(d))  # >= 0 by cap
        absence_total = Σ absence_by_day_map.values()
        employee_norm = work_norm + absence_total

    Cap excused(d) = min(absence_on_d, day_norm(d)) -- ядро (FIX-1). На
    полнодневном 8-ч отсутствии excused = day_norm -> день обнулён в work-части
    (как исключение дня целиком); на частичном (4ч отпуск + 4ч работа)
    вычитается только absence-доля, работа сверх зачёта даёт переработку (Q2).
    Предпраздничный: -1 полный час учитывается в day_norm ДО cap
    (excused = min(8, 7) = 7 на предпраздничном полном отсутствии, кейс G).

    Согласованность absence_total с фактом обеспечивают ВЫЗЫВАЮЩИЕ, не helper:
    absence_by_day_map строится тем же предикатом+cutoff+нормализацией, что и
    absence-доля employee_total на стороне факта (_build_data_matrix). Helper
    принимает карту как есть и суммирует её -- он не отбирает absence и не
    сверяет её с фактом.

    Предусловие (гарантируется валидатором Fsm_6_1_2.validate_total_consistency):
    валидный табель имеет total == Σdaily с допуском 0.5 ч. Malformed-вход
    (итог часов без подённой детализации либо расхождение total/daily свыше
    0.5 ч) ОТВЕРГАЕТСЯ валидатором ДО расчёта нормы -- сюда такой табель не
    доходит. Поэтому absence_total, взятый из absence_by_day_map (источник --
    подённые ячейки daily), согласован с absence-долей факта employee_total.

    Источник year/month -- GUI (authoritative), НЕ ts.year/ts.month (значение
    из ячейки B4 файла, лишь ориентир -- всегда 1 число). Это устраняет
    рассинхрон источника месяца/года между helper и оркестратором.

    Args:
        ts: TimesheetData (нужен fio для логов).
        absence_by_day_map: словарь {день: Σ absence-часов} (из absence_by_day).
        rate: ставка сотрудника (0.5, 1.0 и т.д.).
        end_day: последний день периода (включительно). None -> полный месяц.
        calendar_manager: ProductionCalendarManager (источник статуса дня, SSOT).
        year: год периода (из GUI, authoritative).
        month: месяц периода (из GUI, authoritative).
        calendar_unavailable: флаг недоступности календаря -> сразу None.

    Returns:
        Норма часов (float) или None при недоступности календаря (F-07).
    """
    # F-07: календарь недоступен (предзагрузка упала) -> норму не считаем
    if calendar_unavailable or calendar_manager is None:
        return None

    # Диапазон дней периода (year/month -- из GUI, не из ts)
    if end_day is None:
        last_day = _calendar.monthrange(year, month)[1]
    else:
        last_day = end_day

    days = range(1, last_day + 1)

    # work_norm: Σ по рабочим дням периода (day_norm - excused), где зачёт
    # отсутствия capped дневной нормой (>= 0 by construction).
    work_norm = 0.0
    try:
        for d in days:
            dt = date(year, month, d)
            if not calendar_manager.is_workday(dt):
                continue
            if calendar_manager.is_shortened_day(dt):
                day_norm = max(8 * rate - 1, 0)
            else:
                day_norm = max(8 * rate, 0)
            absence_on_d = absence_by_day_map.get(d, 0.0)
            excused = min(absence_on_d, day_norm)
            work_norm += day_norm - excused
    except RuntimeError:
        # Календарь стал недоступен в процессе (год/день) -> graceful None
        log_warning(
            f"Fsm_6_1_6: производственный календарь недоступен для {ts.fio}, "
            "норма не рассчитана"
        )
        return None

    # absence_total: часы отсутствия входят и в норму, и в факт -> сокращаются
    # в deviation. Работа в день отсутствия сверх зачёта остаётся переработкой.
    absence_total = sum(absence_by_day_map.values())

    employee_norm = work_norm + absence_total
    return employee_norm
