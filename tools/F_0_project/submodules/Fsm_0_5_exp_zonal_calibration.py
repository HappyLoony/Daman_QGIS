# -*- coding: utf-8 -*-
"""
Fsm_0_5_exp — Экспериментальный модуль зональной калибровки МСК.

ИЗОЛИРОВАН от F_0_5. Не влияет на production workflow.
Вызывается только через MCP execute_code.

Цель: вычислить параметры CRS для всей зоны МСК по контрольным точкам,
распределённым по территории.

Два уровня:
1. TM fit: оптимизация lon_0, x_0, y_0 (LDP pipeline)
2. Helmert 7P: оптимизация towgs84 (dX, dY, dZ) через чистую математику

Helmert реализован на чистом Python (math only, без QgsCoordinateTransform),
чтобы не таймаутить MCP при переборе параметров.
"""

import math
import statistics
from typing import List, Tuple, Optional, Dict

# Константы эллипсоида Красовского
KRASS_A = 6378245.0
KRASS_B = 6356863.018773047  # a * (1 - f), f = 1/298.3
KRASS_E2 = 0.006693421622966  # (a^2 - b^2) / a^2

# WGS-84
WGS84_A = 6378137.0
WGS84_B = 6356752.314245179
WGS84_E2 = 0.00669437999014

# Стандартные towgs84 (Position Vector, PROJ convention)
DEFAULT_TOWGS84 = {
    'dX': 23.57, 'dY': -140.95, 'dZ': -79.8,
    'rX': 0.0, 'rY': 0.35, 'rZ': 0.79,
    'dS': -0.22  # ppm
}


def log(msg: str):
    """Логирование в stdout (для MCP execute_code)."""
    print(f"[EXP] {msg}")


# ====================================================================
# Математика: Helmert 7P на чистом Python
# ====================================================================

def geodetic_to_ecef(lat_deg: float, lon_deg: float, h: float,
                     a: float, e2: float) -> Tuple[float, float, float]:
    """Геодезические координаты → ECEF (X, Y, Z)."""
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    N = a / math.sqrt(1 - e2 * sin_lat ** 2)
    X = (N + h) * cos_lat * math.cos(lon)
    Y = (N + h) * cos_lat * math.sin(lon)
    Z = (N * (1 - e2) + h) * sin_lat
    return X, Y, Z


def ecef_to_geodetic(X: float, Y: float, Z: float,
                     a: float, e2: float) -> Tuple[float, float, float]:
    """ECEF → геодезические координаты (итеративный Bowring)."""
    b = a * math.sqrt(1 - e2)
    ep2 = (a ** 2 - b ** 2) / b ** 2
    p = math.sqrt(X ** 2 + Y ** 2)
    lon = math.atan2(Y, X)

    # Начальное приближение
    theta = math.atan2(Z * a, p * b)
    lat = math.atan2(
        Z + ep2 * b * math.sin(theta) ** 3,
        p - e2 * a * math.cos(theta) ** 3
    )

    # 2 итерации для сходимости
    for _ in range(2):
        sin_lat = math.sin(lat)
        N = a / math.sqrt(1 - e2 * sin_lat ** 2)
        lat = math.atan2(Z + e2 * N * sin_lat, p)

    sin_lat = math.sin(lat)
    N = a / math.sqrt(1 - e2 * sin_lat ** 2)
    h = p / math.cos(lat) - N if abs(lat) < math.radians(89) else Z / math.sin(lat) - N * (1 - e2)

    return math.degrees(lat), math.degrees(lon), h


def helmert_transform(X: float, Y: float, Z: float,
                      tw: Dict) -> Tuple[float, float, float]:
    """Position Vector 7-parameter Helmert transformation.

    tw: dict with keys dX, dY, dZ, rX, rY, rZ (arc-seconds), dS (ppm)
    """
    # Углы поворота из arc-seconds в радианы
    rx = math.radians(tw['rX'] / 3600)
    ry = math.radians(tw['rY'] / 3600)
    rz = math.radians(tw['rZ'] / 3600)
    s = 1 + tw['dS'] * 1e-6

    # Position Vector rotation matrix
    Xw = tw['dX'] + s * (X - rz * Y + ry * Z)
    Yw = tw['dY'] + s * (rz * X + Y - rx * Z)
    Zw = tw['dZ'] + s * (-ry * X + rx * Y + Z)

    return Xw, Yw, Zw


def krass_to_wgs84(lat_deg: float, lon_deg: float, h: float = 0.0,
                   tw: Optional[Dict] = None) -> Tuple[float, float, float]:
    """Красовского → WGS-84 через Helmert 7P."""
    if tw is None:
        tw = DEFAULT_TOWGS84
    X, Y, Z = geodetic_to_ecef(lat_deg, lon_deg, h, KRASS_A, KRASS_E2)
    Xw, Yw, Zw = helmert_transform(X, Y, Z, tw)
    return ecef_to_geodetic(Xw, Yw, Zw, WGS84_A, WGS84_E2)


def wgs84_to_webmercator(lat_deg: float, lon_deg: float) -> Tuple[float, float]:
    """WGS-84 → EPSG:3857 (Web Mercator)."""
    x = WGS84_A * math.radians(lon_deg)
    y = WGS84_A * math.log(math.tan(math.pi / 4 + math.radians(lat_deg) / 2))
    return x, y


def webmercator_to_wgs84(x: float, y: float) -> Tuple[float, float]:
    """EPSG:3857 → WGS-84."""
    lon_deg = math.degrees(x / WGS84_A)
    lat_deg = math.degrees(2 * math.atan(math.exp(y / WGS84_A)) - math.pi / 2)
    return lat_deg, lon_deg


def tmerc_forward(lat_deg: float, lon_deg: float,
                  lon_0: float, k_0: float = 1.0,
                  a: float = KRASS_A, e2: float = KRASS_E2) -> Tuple[float, float]:
    """Transverse Mercator прямая проекция (Красовский)."""
    lat = math.radians(lat_deg)
    dlon = math.radians(lon_deg - lon_0)

    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    tan_lat = math.tan(lat)

    N = a / math.sqrt(1 - e2 * sin_lat ** 2)
    T = tan_lat ** 2
    C = e2 / (1 - e2) * cos_lat ** 2
    A_val = dlon * cos_lat

    # Meridian arc
    e4 = e2 ** 2
    e6 = e2 ** 3
    M = a * (
        (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * lat
        - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * lat)
        + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * lat)
        - (35 * e6 / 3072) * math.sin(6 * lat)
    )

    A2 = A_val ** 2
    A4 = A2 ** 2
    A6 = A4 * A2

    easting = k_0 * N * (
        A_val
        + (1 - T + C) * A2 * A_val / 6
        + (5 - 18 * T + T ** 2 + 72 * C) * A4 * A_val / 120
    )

    northing = k_0 * (
        M + N * tan_lat * (
            A2 / 2
            + (5 - T + 9 * C + 4 * C ** 2) * A4 / 24
            + (61 - 58 * T + T ** 2 + 600 * C) * A6 / 720
        )
    )

    return easting, northing


# ====================================================================
# Основной расчёт
# ====================================================================

def compute_residuals(
    pairs: List[Tuple[Tuple[float, float], Tuple[float, float]]],
    lon_0: float,
    tw: Optional[Dict] = None
) -> Tuple[float, float, float, List[float], List[float], List[float]]:
    """Вычислить x_0, y_0, RMSE для заданных lon_0 и towgs84.

    Полностью на чистом Python — без QGIS CRS.

    Pipeline: correct_3857 → WGS84 → Krass (inv Helmert) → TM forward
    Но проще: correct_3857 → WGS84 lat/lon → TM на Красовском с towgs84
    Фактически: мы идём обратным путём.

    Правильный LDP pipeline:
    - correct_3857 → WGS84 lat/lon
    - WGS84 lat/lon → (inv Helmert) → Krass lat/lon
    - Krass lat/lon → TM forward → projected (E, N)
    - x_0 = median(wrong_E - projected_E)
    - y_0 = median(wrong_N - projected_N)
    """
    if tw is None:
        tw = DEFAULT_TOWGS84

    # Инвертированный Helmert: WGS84 → Krass
    # Для малых углов и масштаба ≈ инвертируем знаки
    tw_inv = {
        'dX': -tw['dX'], 'dY': -tw['dY'], 'dZ': -tw['dZ'],
        'rX': -tw['rX'], 'rY': -tw['rY'], 'rZ': -tw['rZ'],
        'dS': -tw['dS']
    }

    dx_list = []
    dy_list = []

    for (wrong_x, wrong_y), (c3857_x, c3857_y) in pairs:
        # 3857 → WGS84
        lat_wgs, lon_wgs = webmercator_to_wgs84(c3857_x, c3857_y)

        # WGS84 → Krass (через инвертированный Helmert)
        lat_kr, lon_kr, _ = krass_to_wgs84(lat_wgs, lon_wgs, 0.0, tw_inv)

        # Krass → TM
        e, n = tmerc_forward(lat_kr, lon_kr, lon_0)

        dx_list.append(wrong_x - e)
        dy_list.append(wrong_y - n)

    x_0 = statistics.median(dx_list)
    y_0 = statistics.median(dy_list)

    errors = []
    for i in range(len(dx_list)):
        err = math.sqrt((dx_list[i] - x_0) ** 2 + (dy_list[i] - y_0) ** 2)
        errors.append(err)

    rmse = math.sqrt(sum(e ** 2 for e in errors) / len(errors)) if errors else float('inf')

    return x_0, y_0, rmse, errors, dx_list, dy_list


def optimize_lon0(
    pairs: List[Tuple[Tuple[float, float], Tuple[float, float]]],
    tw: Optional[Dict] = None,
    lon_min: float = 20.0,
    lon_max: float = 180.0,
    coarse_step: float = 1.0,
    fine_tol: float = 1e-6
) -> Tuple[float, float, float, float]:
    """Оптимизация lon_0: грубый поиск + золотое сечение.

    Returns: (lon_0, x_0, y_0, rmse)
    """
    if tw is None:
        tw = DEFAULT_TOWGS84

    # Грубый поиск
    best_lon0 = lon_min
    best_rmse = float('inf')

    lon = lon_min
    while lon <= lon_max:
        _, _, rmse, _, _, _ = compute_residuals(pairs, lon, tw)
        if rmse < best_rmse:
            best_rmse = rmse
            best_lon0 = lon
        lon += coarse_step

    log(f"Coarse: best lon_0={best_lon0:.1f}, RMSE={best_rmse:.4f}m")

    # Золотое сечение
    phi = (1 + math.sqrt(5)) / 2
    a_gs = max(lon_min, best_lon0 - coarse_step)
    b_gs = min(lon_max, best_lon0 + coarse_step)

    for iteration in range(60):
        if abs(b_gs - a_gs) < fine_tol:
            break
        c = b_gs - (b_gs - a_gs) / phi
        d = a_gs + (b_gs - a_gs) / phi
        _, _, rc, _, _, _ = compute_residuals(pairs, c, tw)
        _, _, rd, _, _, _ = compute_residuals(pairs, d, tw)
        if rc < rd:
            b_gs = d
        else:
            a_gs = c

    optimal_lon0 = (a_gs + b_gs) / 2
    x_0, y_0, rmse, errors, _, _ = compute_residuals(pairs, optimal_lon0, tw)

    log(f"Fine: lon_0={optimal_lon0:.6f}, RMSE={rmse:.6f}m, x_0={x_0:.2f}, y_0={y_0:.2f}")

    return optimal_lon0, x_0, y_0, rmse


def optimize_towgs84(
    pairs: List[Tuple[Tuple[float, float], Tuple[float, float]]],
    lon_0: float,
    base_tw: Optional[Dict] = None,
    search_range: float = 5.0,
    search_step: float = 1.0
) -> Tuple[Dict, float, float, float, float]:
    """Оптимизация dX, dY, dZ последовательно (1D search each).

    Returns: (best_tw, x_0, y_0, rmse, baseline_rmse)
    """
    if base_tw is None:
        base_tw = dict(DEFAULT_TOWGS84)

    tw = dict(base_tw)
    _, _, baseline_rmse, _, _, _ = compute_residuals(pairs, lon_0, tw)
    log(f"Baseline RMSE: {baseline_rmse:.6f}m")

    # Оптимизация dX
    best_rmse = baseline_rmse
    for i in range(int(-search_range / search_step), int(search_range / search_step) + 1):
        tw_test = dict(tw)
        tw_test['dX'] = base_tw['dX'] + i * search_step
        _, _, r, _, _, _ = compute_residuals(pairs, lon_0, tw_test)
        if r < best_rmse:
            best_rmse = r
            tw['dX'] = tw_test['dX']
    log(f"After dX={tw['dX']:.2f}: RMSE={best_rmse:.6f}m")

    # Оптимизация dY
    for i in range(int(-search_range / search_step), int(search_range / search_step) + 1):
        tw_test = dict(tw)
        tw_test['dY'] = base_tw['dY'] + i * search_step
        _, _, r, _, _, _ = compute_residuals(pairs, lon_0, tw_test)
        if r < best_rmse:
            best_rmse = r
            tw['dY'] = tw_test['dY']
    log(f"After dY={tw['dY']:.2f}: RMSE={best_rmse:.6f}m")

    # Оптимизация dZ
    for i in range(int(-search_range / search_step), int(search_range / search_step) + 1):
        tw_test = dict(tw)
        tw_test['dZ'] = base_tw['dZ'] + i * search_step
        _, _, r, _, _, _ = compute_residuals(pairs, lon_0, tw_test)
        if r < best_rmse:
            best_rmse = r
            tw['dZ'] = tw_test['dZ']
    log(f"After dZ={tw['dZ']:.2f}: RMSE={best_rmse:.6f}m")

    x_0, y_0, rmse, _, _, _ = compute_residuals(pairs, lon_0, tw)

    log(f"Optimized towgs84: dX={tw['dX']}, dY={tw['dY']}, dZ={tw['dZ']}")
    log(f"RMSE: {baseline_rmse:.6f} -> {rmse:.6f}m ({(baseline_rmse-rmse)/baseline_rmse*100:.1f}% improvement)")

    return tw, x_0, y_0, rmse, baseline_rmse


def run_full_experiment(
    pairs: List[Tuple[Tuple[float, float], Tuple[float, float]]],
    optimize_tw: bool = True
) -> Dict:
    """Полный эксперимент: lon_0 + towgs84 оптимизация.

    Args:
        pairs: список ((wrong_x, wrong_y), (correct_3857_x, correct_3857_y))
        optimize_tw: оптимизировать ли towgs84

    Returns: dict с результатами
    """
    log(f"=== ZONAL CALIBRATION EXPERIMENT ===")
    log(f"Pairs: {len(pairs)}")

    # Extent
    wxs = [p[0][0] for p in pairs]
    wys = [p[0][1] for p in pairs]
    log(f"Wrong extent: X=[{min(wxs):.0f}, {max(wxs):.0f}], Y=[{min(wys):.0f}, {max(wys):.0f}]")
    log(f"Span: {(max(wxs)-min(wxs))/1000:.0f} x {(max(wys)-min(wys))/1000:.0f} km")

    # Step 1: Optimize lon_0 with default towgs84
    log(f"\n--- Step 1: Optimize lon_0 ---")
    lon_0, x_0, y_0, rmse = optimize_lon0(pairs)

    result = {
        'lon_0': lon_0,
        'x_0': x_0,
        'y_0': y_0,
        'rmse_step1': rmse,
        'towgs84': dict(DEFAULT_TOWGS84),
    }

    # Per-point errors
    _, _, _, errors, dx_list, dy_list = compute_residuals(pairs, lon_0)
    log(f"\nPer-point errors (Step 1):")
    for i, ((wx, wy), _) in enumerate(pairs):
        log(f"  pt{i+1}: ({wx:.0f}, {wy:.0f}) err={errors[i]:.4f}m dx={dx_list[i]-x_0:.4f} dy={dy_list[i]-y_0:.4f}")

    if optimize_tw:
        # Step 2: Optimize towgs84
        log(f"\n--- Step 2: Optimize towgs84 (dX, dY, dZ) ---")
        tw_opt, x_0_tw, y_0_tw, rmse_tw, _ = optimize_towgs84(pairs, lon_0)

        # Re-optimize lon_0 with new towgs84
        log(f"\n--- Step 3: Re-optimize lon_0 with new towgs84 ---")
        lon_0_2, x_0_2, y_0_2, rmse_2 = optimize_lon0(pairs, tw_opt)

        result.update({
            'lon_0': lon_0_2,
            'x_0': x_0_2,
            'y_0': y_0_2,
            'rmse_step2': rmse_tw,
            'rmse_step3': rmse_2,
            'towgs84': tw_opt,
        })

        # Final per-point
        _, _, _, errors2, dx2, dy2 = compute_residuals(pairs, lon_0_2, tw_opt)
        log(f"\nPer-point errors (Final):")
        for i, ((wx, wy), _) in enumerate(pairs):
            log(f"  pt{i+1}: ({wx:.0f}, {wy:.0f}) err={errors2[i]:.4f}m")

    log(f"\n=== RESULT ===")
    log(f"lon_0 = {result['lon_0']:.6f}")
    log(f"x_0   = {result['x_0']:.4f}")
    log(f"y_0   = {result['y_0']:.4f}")
    tw = result['towgs84']
    log(f"towgs84 = {tw['dX']},{tw['dY']},{tw['dZ']},{tw['rX']},{tw['rY']},{tw['rZ']},{tw['dS']}")
    rmse_key = 'rmse_step3' if 'rmse_step3' in result else 'rmse_step1'
    log(f"RMSE  = {result[rmse_key]:.6f} m")

    return result


# ====================================================================
# Horner Pipeline: вычисление коэффициентов и регистрация в QGIS
# ====================================================================

# Порядок мономов в PROJ horner deg=3 (10 коэффициентов):
# fwd_u: 1, U, U², U³, V, UV, U²V, V², UV², V³
# fwd_v: 1, V, V², V³, U, UV, UV², U², U²V, U³
#
# Стандартный порядок: c00, c10, c01, c20, c11, c02, c30, c21, c12, c03
# Маппинг std → PROJ fwd_u: [0,1,3,6,2,4,7,5,8,9]
# Маппинг std → PROJ fwd_v: [0,2,5,9,1,4,8,3,7,6]

_STD_TO_PROJ_U = [0, 1, 3, 6, 2, 4, 7, 5, 8, 9]
_STD_TO_PROJ_V = [0, 2, 5, 9, 1, 4, 8, 3, 7, 6]


def compute_horner_coefficients(
    pairs: List[Tuple[Tuple[float, float], Tuple[float, float]]],
    lon_0: float,
    x_0: float,
    y_0: float,
    towgs84_str: str,
    deg: int = 3
) -> Optional[Dict]:
    """Вычислить коэффициенты horner полинома из контрольных точек.

    Требует QGIS (QgsCoordinateTransform) для трансформации 3857→TM.

    Args:
        pairs: список ((wrong_x, wrong_y), (correct_3857_x, correct_3857_y))
        lon_0: центральный меридиан
        x_0, y_0: false easting/northing
        towgs84_str: строка towgs84 (e.g., "23.57,-140.95,-79.8,0,0.35,0.79,-0.22")
        deg: степень полинома (2 или 3)

    Returns:
        dict с ключами: fwd_u, fwd_v, origin_e, origin_n, pipeline, max_err, rmse
        или None при ошибке
    """
    try:
        from qgis.core import (
            QgsCoordinateTransform, QgsCoordinateReferenceSystem,
            QgsPointXY, QgsProject
        )
    except ImportError:
        log("QGIS не доступен")
        return None

    n = len(pairs)
    ncoeffs = (deg + 1) * (deg + 2) // 2
    if n < ncoeffs + 4:
        log(f"Недостаточно точек: {n}, нужно минимум {ncoeffs + 4} для deg={deg}")
        return None

    # CRS с x_0=0, y_0=0 для получения "чистых" проецированных координат
    proj_str = (
        f"+proj=tmerc +lat_0=0 +lon_0={lon_0} +k_0=1 +x_0=0 +y_0=0 "
        f"+ellps=krass +towgs84={towgs84_str} +units=m +no_defs"
    )
    crs = QgsCoordinateReferenceSystem()
    crs.createFromProj(proj_str)
    if not crs.isValid():
        log("Невалидная CRS")
        return None

    tr = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem("EPSG:3857"), crs, QgsProject.instance()
    )

    # Вычисляем residuals: wrong - (projected_correct + x_0, y_0)
    src_u, src_v, res_dx, res_dy = [], [], [], []
    for (wx, wy), (cx, cy) in pairs:
        ref = tr.transform(QgsPointXY(cx, cy))
        u = ref.x()
        v = ref.y()
        dx = (wx - x_0) - u
        dy = (wy - y_0) - v
        src_u.append(u)
        src_v.append(v)
        res_dx.append(dx)
        res_dy.append(dy)

    origin_e = statistics.mean(src_u)
    origin_n = statistics.mean(src_v)
    log(f"Horner origin (raw): ({origin_e:.2f}, {origin_n:.2f})")
    log(f"Horner origin (МСК): ({origin_e + x_0:.2f}, {origin_n + y_0:.2f})")

    # Нормализация
    scale = max(
        max(abs(u - origin_e) for u in src_u),
        max(abs(v - origin_n) for v in src_v)
    )
    if scale < 1:
        scale = 1
    nu = [(u - origin_e) / scale for u in src_u]
    nv = [(v - origin_n) / scale for v in src_v]

    # Построение матрицы мономов (стандартный порядок)
    # deg=2: 1, u, v, u², uv, v² (6)
    # deg=3: 1, u, v, u², uv, v², u³, u²v, uv², v³ (10)
    def monomial_powers(d):
        """Степени (i,j) в стандартном порядке для deg=d."""
        powers = []
        for order in range(d + 1):
            for j in range(order + 1):
                i = order - j
                powers.append((i, j))
        return powers

    powers = monomial_powers(deg)
    nc = len(powers)

    def build_row(u, v):
        return [u ** p[0] * v ** p[1] for p in powers]

    # LSQ: A^T*A * c = A^T*b
    ATA = [[0.0] * nc for _ in range(nc)]
    ATb_dx = [0.0] * nc
    ATb_dy = [0.0] * nc

    for i in range(n):
        row = build_row(nu[i], nv[i])
        for j in range(nc):
            for k in range(nc):
                ATA[j][k] += row[j] * row[k]
            ATb_dx[j] += row[j] * res_dx[i]
            ATb_dy[j] += row[j] * res_dy[i]

    # Gauss solve
    def gauss(M, b):
        sz = len(M)
        aug = [M[i][:] + [b[i]] for i in range(sz)]
        for i in range(sz):
            mx = max(range(i, sz), key=lambda r: abs(aug[r][i]))
            aug[i], aug[mx] = aug[mx], aug[i]
            if abs(aug[i][i]) < 1e-30:
                return None
            for j in range(i + 1, sz):
                f = aug[j][i] / aug[i][i]
                for k in range(i, sz + 1):
                    aug[j][k] -= f * aug[i][k]
        x = [0.0] * sz
        for i in range(sz - 1, -1, -1):
            x[i] = (aug[i][sz] - sum(aug[i][j] * x[j] for j in range(i + 1, sz))) / aug[i][i]
        return x

    cu_norm = gauss(ATA, ATb_dx)
    cv_norm = gauss(ATA, ATb_dy)
    if cu_norm is None or cv_norm is None:
        log("Сингулярная матрица — полином не решается")
        return None

    # Денормализация
    cu_real = [cu_norm[k] / (scale ** (powers[k][0] + powers[k][1])) for k in range(nc)]
    cv_real = [cv_norm[k] / (scale ** (powers[k][0] + powers[k][1])) for k in range(nc)]

    # Верификация
    errors = []
    for i in range(n):
        u, v = src_u[i] - origin_e, src_v[i] - origin_n
        pred_dx = sum(cu_real[k] * u ** powers[k][0] * v ** powers[k][1] for k in range(nc))
        pred_dy = sum(cv_real[k] * u ** powers[k][0] * v ** powers[k][1] for k in range(nc))
        err = math.sqrt((res_dx[i] - pred_dx) ** 2 + (res_dy[i] - pred_dy) ** 2)
        errors.append(err)

    rmse = math.sqrt(sum(e ** 2 for e in errors) / n)
    max_err = max(errors)
    log(f"Poly{deg} fit: RMSE={rmse * 1000:.2f}mm, Max={max_err * 1000:.2f}mm, n={n}")

    # ================================================================
    # Обратный полином (inv): МСК → TM
    # Фитируем НАПРЯМУЮ в PROJ порядке мономов (crossed ordering):
    # inv_u: [1, U, U², U³, V, UV, U²V, V², UV², V³] (inner=U)
    # inv_v: [1, V, V², V³, U, UV, UV², U², U²V, U³] (inner=V)
    # ================================================================
    msk_u = [(wx - x_0) for (wx, wy), _ in pairs]
    msk_v = [(wy - y_0) for (wx, wy), _ in pairs]

    inv_origin_e = statistics.mean(msk_u)
    inv_origin_n = statistics.mean(msk_v)

    inv_scale = max(
        max(abs(u - inv_origin_e) for u in msk_u),
        max(abs(v - inv_origin_n) for v in msk_v)
    )
    if inv_scale < 1:
        inv_scale = 1
    inv_nu = [(u - inv_origin_e) / inv_scale for u in msk_u]
    inv_nv = [(v - inv_origin_n) / inv_scale for v in msk_v]

    # PROJ crossed monomial powers:
    # fwd_u order: grouped by V-power, U ascending within each group
    # fwd_v order: grouped by U-power, V ascending within each group
    def proj_u_powers(d):
        """Степени (i,j) в порядке PROJ fwd_u: V^k groups, U ascending."""
        p = []
        for vp in range(d + 1):
            for up in range(d + 1 - vp):
                p.append((up, vp))
        return p

    def proj_v_powers(d):
        """Степени (i,j) в порядке PROJ fwd_v: U^k groups, V ascending."""
        p = []
        for up in range(d + 1):
            for vp in range(d + 1 - up):
                p.append((up, vp))
        return p

    pu_powers = proj_u_powers(deg)
    pv_powers = proj_v_powers(deg)

    def build_row_proj(u, v, proj_powers):
        return [u ** p[0] * v ** p[1] for p in proj_powers]

    # Target: full source coords (TM + x_0/y_0), not residuals
    # inv_poly(dE, dN) = source_coord directly
    target_u = [src_u[i] + x_0 for i in range(n)]
    target_v = [src_v[i] + y_0 for i in range(n)]

    # LSQ for inv_u (PROJ fwd_u ordering)
    inv_ATA_u = [[0.0] * nc for _ in range(nc)]
    inv_ATb_u = [0.0] * nc
    for i in range(n):
        row = build_row_proj(inv_nu[i], inv_nv[i], pu_powers)
        for j in range(nc):
            for k in range(nc):
                inv_ATA_u[j][k] += row[j] * row[k]
            inv_ATb_u[j] += row[j] * target_u[i]

    # LSQ for inv_v (PROJ fwd_v ordering)
    inv_ATA_v = [[0.0] * nc for _ in range(nc)]
    inv_ATb_v = [0.0] * nc
    for i in range(n):
        row = build_row_proj(inv_nu[i], inv_nv[i], pv_powers)
        for j in range(nc):
            for k in range(nc):
                inv_ATA_v[j][k] += row[j] * row[k]
            inv_ATb_v[j] += row[j] * target_v[i]

    inv_u_norm = gauss(inv_ATA_u, inv_ATb_u)
    inv_v_norm = gauss(inv_ATA_v, inv_ATb_v)
    if inv_u_norm is None or inv_v_norm is None:
        log("Сингулярная матрица для обратного полинома")
        return None

    # Денормализация (каждый коэффициент по своему набору степеней)
    inv_u_proj = [inv_u_norm[k] / (inv_scale ** (pu_powers[k][0] + pu_powers[k][1]))
                  for k in range(nc)]
    inv_v_proj = [inv_v_norm[k] / (inv_scale ** (pv_powers[k][0] + pv_powers[k][1]))
                  for k in range(nc)]

    # Верификация inv
    inv_errors = []
    for i in range(n):
        row_u = build_row_proj(
            (msk_u[i] - inv_origin_e), (msk_v[i] - inv_origin_n), pu_powers)
        row_v = build_row_proj(
            (msk_u[i] - inv_origin_e), (msk_v[i] - inv_origin_n), pv_powers)
        pred_u = sum(inv_u_proj[k] * row_u[k] for k in range(nc))
        pred_v = sum(inv_v_proj[k] * row_v[k] for k in range(nc))
        err = math.sqrt((target_u[i] - pred_u) ** 2 + (target_v[i] - pred_v) ** 2)
        inv_errors.append(err)

    inv_rmse = math.sqrt(sum(e ** 2 for e in inv_errors) / n)
    inv_max = max(inv_errors)
    log(f"Inv Poly{deg} fit (PROJ order): RMSE={inv_rmse * 1000:.2f}mm, Max={inv_max * 1000:.2f}mm")

    inv_msk_origin_e = inv_origin_e + x_0
    inv_msk_origin_n = inv_origin_n + y_0

    # ================================================================
    # Конвертация forward в PROJ порядок
    # ================================================================
    if deg == 3:
        mapping_u = _STD_TO_PROJ_U
        mapping_v = _STD_TO_PROJ_V
    elif deg == 2:
        mapping_u = [0, 1, 3, 2, 4, 5]
        mapping_v = [0, 2, 5, 1, 4, 3]
    else:
        log(f"deg={deg} не поддерживается")
        return None

    fwd_u_proj = [cu_real[mapping_u[k]] for k in range(nc)]
    fwd_v_proj = [cv_real[mapping_v[k]] for k in range(nc)]
    fwd_u_proj[1] += 1.0
    fwd_v_proj[1] += 1.0
    msk_origin_e = origin_e + x_0
    msk_origin_n = origin_n + y_0
    fwd_u_proj[0] += msk_origin_e
    fwd_v_proj[0] += msk_origin_n

    # Pipeline строка с fwd и inv коэффициентами.
    # inv_u_proj/inv_v_proj уже в PROJ порядке (crossed ordering).
    # M_1 регистрирует ТОЛЬКО forward direction (3857→project).
    # QGIS auto-inverts pipeline, используя inv коэффициенты.
    cu_s = ",".join(f"{c:.15e}" for c in fwd_u_proj)
    cv_s = ",".join(f"{c:.15e}" for c in fwd_v_proj)
    inv_cu_s = ",".join(f"{c:.15e}" for c in inv_u_proj)
    inv_cv_s = ",".join(f"{c:.15e}" for c in inv_v_proj)

    pipeline = (
        f"+proj=pipeline "
        f"+step +inv +proj=webmerc +ellps=WGS84 "
        f"+step +proj=tmerc +lat_0=0 +lon_0={lon_0} +k_0=1 "
        f"+x_0={x_0} +y_0={y_0} +ellps=krass "
        f"+towgs84={towgs84_str} "
        f"+step +proj=horner +ellps=krass +deg={deg} "
        f"+fwd_origin={msk_origin_e:.4f},{msk_origin_n:.4f} "
        f"+fwd_u={cu_s} "
        f"+fwd_v={cv_s} "
        f"+inv_origin={inv_msk_origin_e:.4f},{inv_msk_origin_n:.4f} "
        f"+inv_u={inv_cu_s} "
        f"+inv_v={inv_cv_s}"
    )

    log(f"Pipeline length: {len(pipeline)} chars")

    return {
        'fwd_u': fwd_u_proj,
        'fwd_v': fwd_v_proj,
        'origin_e': msk_origin_e,
        'origin_n': msk_origin_n,
        'pipeline': pipeline,
        'max_err': max_err,
        'rmse': rmse,
        'deg': deg,
        'n_points': n,
        'cu_std': cu_real,
        'cv_std': cv_real,
    }


def register_pipeline_in_qgis(
    pipeline_str: str,
    src_crs_authid: str,
    dst_crs_authid: str = "EPSG:3857"
) -> bool:
    """Зарегистрировать pipeline как coordinate operation в текущем проекте QGIS.

    Args:
        pipeline_str: полная PROJ pipeline строка
        src_crs_authid: authid исходной CRS (e.g., "USER:100010")
        dst_crs_authid: authid целевой CRS (default "EPSG:3857")

    Returns:
        True если успешно
    """
    try:
        from qgis.core import QgsCoordinateReferenceSystem, QgsProject

        src_crs = QgsCoordinateReferenceSystem(src_crs_authid)
        dst_crs = QgsCoordinateReferenceSystem(dst_crs_authid)

        if not src_crs.isValid() or not dst_crs.isValid():
            log(f"Невалидная CRS: src={src_crs_authid}, dst={dst_crs_authid}")
            return False

        # DO NOT register pipeline as coordinate operation.
        # Horner polynomial has only +fwd coefficients — QGIS auto-inverts
        # registered operations for the reverse direction, producing ~1000km
        # coordinate errors that break XYZ tile fetching.
        # Pipeline is used directly by F_0_5 calibration functions.
        log(f"Pipeline доступен: {src_crs_authid} <-> {dst_crs_authid} (не регистрируется как coordinate operation)")
        return True

    except Exception as e:
        log(f"Ошибка регистрации pipeline: {e}")
        return False
