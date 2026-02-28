# -*- coding: utf-8 -*-
"""
Shared Helmert 2D (4 parameters) solver.

Pure math module - no CRS, no QGIS dependencies.
Used by both F_0_5 (projection refinement) and F_0_6 (coordinate transform).

2D Helmert (similarity transform):
    X' = dx + a*X - b*Y
    Y' = dy + b*X + a*Y

Where:
    a = scale * cos(theta)
    b = scale * sin(theta)

Parameters: dx, dy, scale, rotation
Minimum: 2 points (exact), 4+ recommended (overdetermined)

Sources:
- https://en.wikipedia.org/wiki/Helmert_transformation
- https://proj.org/en/stable/operations/transformations/helmert.html
"""

import math
from typing import List, Tuple
from dataclasses import dataclass


@dataclass
class Helmert2DResult:
    """Result of 2D Helmert transformation calculation."""
    dx: float  # Translation X (meters)
    dy: float  # Translation Y (meters)
    scale: float  # Scale factor (dimensionless, ~1.0)
    rotation_deg: float  # Rotation (degrees)
    rotation_arcsec: float  # Rotation (arc seconds, for PROJ)
    rmse: float  # RMSE (meters)
    residuals: List[float]  # Per-point residuals
    success: bool


def calculate_rmse(residuals: List[float]) -> float:
    """
    Calculate RMSE from a list of residual values.

    Parameters:
        residuals: List of residual distances (meters)

    Returns:
        RMSE in meters
    """
    if not residuals:
        return 0.0
    return math.sqrt(sum(e ** 2 for e in residuals) / len(residuals))


def calculate_helmert_2d(
    src_points: List[Tuple[float, float]],
    dst_points: List[Tuple[float, float]]
) -> Helmert2DResult:
    """
    Calculate 4 parameters of 2D Helmert via Least Squares.

    Model:
        X' = dx + a*X - b*Y
        Y' = dy + b*X + a*Y

    Where:
        a = scale * cos(theta)
        b = scale * sin(theta)

    Parameters:
        src_points: Source points [(x1,y1), (x2,y2), ...]
        dst_points: Target points [(x1',y1'), (x2',y2'), ...]

    Returns:
        Helmert2DResult with transformation parameters
    """
    n = len(src_points)

    if n < 2:
        return Helmert2DResult(
            dx=0, dy=0, scale=1.0, rotation_deg=0,
            rotation_arcsec=0, rmse=float('inf'),
            residuals=[], success=False
        )

    # Centroids for numerical stability
    src_cx = sum(p[0] for p in src_points) / n
    src_cy = sum(p[1] for p in src_points) / n
    dst_cx = sum(p[0] for p in dst_points) / n
    dst_cy = sum(p[1] for p in dst_points) / n

    # Centered sums
    sum_dx_dx_dy_dy = sum(
        (s[0] - src_cx) ** 2 + (s[1] - src_cy) ** 2
        for s in src_points
    )

    if sum_dx_dx_dy_dy < 1e-10:
        return Helmert2DResult(
            dx=dst_cx - src_cx, dy=dst_cy - src_cy,
            scale=1.0, rotation_deg=0, rotation_arcsec=0,
            rmse=0.0, residuals=[0.0] * n, success=True
        )

    sum_dx_dxp_dy_dyp = sum(
        (s[0] - src_cx) * (d[0] - dst_cx) + (s[1] - src_cy) * (d[1] - dst_cy)
        for s, d in zip(src_points, dst_points)
    )
    sum_dx_dyp_dy_dxp = sum(
        (s[0] - src_cx) * (d[1] - dst_cy) - (s[1] - src_cy) * (d[0] - dst_cx)
        for s, d in zip(src_points, dst_points)
    )

    # Parameters a, b
    a = sum_dx_dxp_dy_dyp / sum_dx_dx_dy_dy
    b = sum_dx_dyp_dy_dxp / sum_dx_dx_dy_dy

    # Scale and rotation
    scale = math.sqrt(a ** 2 + b ** 2)
    rotation_rad = math.atan2(b, a)
    rotation_deg = math.degrees(rotation_rad)
    rotation_arcsec = rotation_deg * 3600

    # Translation (accounting for centering)
    dx = dst_cx - (a * src_cx - b * src_cy)
    dy = dst_cy - (b * src_cx + a * src_cy)

    # Residuals
    residuals = []
    for (sx, sy), (dx_t, dy_t) in zip(src_points, dst_points):
        tx = dx + a * sx - b * sy
        ty = dy + b * sx + a * sy
        residual = math.sqrt((tx - dx_t) ** 2 + (ty - dy_t) ** 2)
        residuals.append(residual)

    rmse = calculate_rmse(residuals)

    return Helmert2DResult(
        dx=dx,
        dy=dy,
        scale=scale,
        rotation_deg=rotation_deg,
        rotation_arcsec=rotation_arcsec,
        rmse=rmse,
        residuals=residuals,
        success=True
    )


def transform_point(
    x: float,
    y: float,
    params: Helmert2DResult
) -> Tuple[float, float]:
    """
    Apply 2D Helmert transformation to a single point.

    Parameters:
        x, y: Source coordinates
        params: Transformation parameters

    Returns:
        (x', y'): Transformed coordinates
    """
    a = params.scale * math.cos(math.radians(params.rotation_deg))
    b = params.scale * math.sin(math.radians(params.rotation_deg))

    x_new = params.dx + a * x - b * y
    y_new = params.dy + b * x + a * y

    return (x_new, y_new)


def inverse_transform_point(
    x: float,
    y: float,
    params: Helmert2DResult
) -> Tuple[float, float]:
    """
    Inverse 2D Helmert transformation.

    Parameters:
        x, y: Transformed coordinates
        params: Transformation parameters

    Returns:
        (x_orig, y_orig): Original coordinates
    """
    a = params.scale * math.cos(math.radians(params.rotation_deg))
    b = params.scale * math.sin(math.radians(params.rotation_deg))

    # Inverse matrix: det = a^2 + b^2 = scale^2
    det = params.scale ** 2

    if det < 1e-10:
        return (x, y)

    # Remove translation
    x_shifted = x - params.dx
    y_shifted = y - params.dy

    # Inverse transform
    x_orig = (a * x_shifted + b * y_shifted) / det
    y_orig = (-b * x_shifted + a * y_shifted) / det

    return (x_orig, y_orig)
