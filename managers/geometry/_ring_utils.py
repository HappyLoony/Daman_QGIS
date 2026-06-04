# -*- coding: utf-8 -*-
"""
Canonical ring-helpers (geometry primitive layer).

Один источник правды для:
- is_clockwise(points) — Shoelace formula, CW в мат.СК = signed_area*2 < 0
- find_nw_point_index(points) — индекс ближайшей к (min_x, max_y) точки
- rotate_to_nw(points) — ротация кольца к старту с NW-точки

Используется M_20 (виртуальная нумерация) и M_47 (физическая нормализация).
Без зависимостей на QGIS API — чистые tuples/lists координат (x, y).

Извлечено из M_20_PointNumberingManager (Phase 0.5, 2026-05-30) для устранения
конфликта «3 источника правды + private import». M_20 staticmethods стали thin
facade, делегирующими сюда.
"""

from typing import List, Tuple

__all__ = ['is_clockwise', 'find_nw_point_index', 'rotate_to_nw']


def is_clockwise(points: List[Tuple[float, float]]) -> bool:
    """Проверка ориентации кольца по часовой стрелке (Shoelace formula).

    В QGIS (x=easting, y=northing) — стандартная математическая СК.
    CW на карте (north-up) соответствует отрицательной знаковой площади.

    Вырожденные кольца (<3 точек) считаются CW (нечего разворачивать).

    Args:
        points: Список кортежей (x, y) координат кольца (без замыкающей).

    Returns:
        True если обход по часовой стрелке (signed_area*2 < 0).
    """
    if len(points) < 3:
        return True

    signed_area_2 = 0.0
    n = len(points)
    for i in range(n):
        j = (i + 1) % n
        signed_area_2 += points[i][0] * points[j][1]
        signed_area_2 -= points[j][0] * points[i][1]

    # signed_area_2 < 0 → CW в математической СК → CW на карте
    return signed_area_2 < 0


def find_nw_point_index(points: List[Tuple[float, float]]) -> int:
    """Найти индекс точки, ближайшей к СЗ углу MBR кольца.

    СЗ угол MBR в QGIS координатах: (min_x, max_y),
    где x = easting (восток), y = northing (север).

    Args:
        points: Список кортежей (x, y) координат кольца.

    Returns:
        Индекс СЗ точки (0-based). 0 для пустого списка.
    """
    if not points:
        return 0

    min_x = min(p[0] for p in points)
    max_y = max(p[1] for p in points)

    best_idx = 0
    best_dist_sq = float('inf')
    for idx, pt in enumerate(points):
        dist_sq = (pt[0] - min_x) ** 2 + (pt[1] - max_y) ** 2
        if dist_sq < best_dist_sq:
            best_dist_sq = dist_sq
            best_idx = idx

    return best_idx


def rotate_to_nw(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Ротация кольца к старту с NW-точки.

    Замыкающая точка НЕ требуется и не добавляется (работа с открытым кольцом).

    Args:
        points: Список кортежей (x, y) координат кольца (без замыкающей).

    Returns:
        Новый список с началом в NW-точке. Исходный не мутируется.
    """
    if not points or len(points) < 2:
        return list(points)
    idx = find_nw_point_index(points)
    if idx == 0:
        return list(points)
    return points[idx:] + points[:idx]
