# -*- coding: utf-8 -*-
"""
Fsm_1_1_8_2 - Извлечение геометрии из XML interact_entry_boundaries

Тонкая обёртка над Fsm_1_1_4_3.extract_geometry из импортёра выписок ЕГРН.

EntitySpatial v2.0.1 - один и тот же XML-формат для геометрии в:
- КПТ (Fsm_1_1_5_2_geometry)
- Выписках ЕГРН (Fsm_1_1_4_3_geometry)
- Уведомлениях о границах (этот модуль)

Поведение:
- X/Y swap для российских МСК (X=North в XML -> Y=East в QGIS и наоборот)
- M-координата хранит delta_geopoint (погрешность точки)
- Multi-contour: outer ring + дыры (interior rings) определяются по площади
- Координаты НЕ округляются (точность 0.01м сохраняется из XML "как есть")

ВАЖНО: Перед вызовом этой функции исходный XML-элемент должен иметь
"стрипнутые" namespaces (elem.tag = localname) - extract_geometry ищет
теги через .findall('.//contour') и .findall('.//spatial_element'),
что работает только при отсутствии namespace prefix.
"""

from typing import Dict, Optional
from qgis.core import QgsGeometry

from ..Fsm_1_1_4_vypiska_importer.Fsm_1_1_4_3_geometry import extract_geometry


def extract_iboundary_geometry(contours_location_element) -> Dict[str, QgsGeometry]:
    """
    Извлечь геометрию из <contours_location> уведомления о границах.

    Делегирует обработку существующему парсеру EntitySpatial v2.0.1
    из импортёра выписок ЕГРН (Fsm_1_1_4_3_geometry.extract_geometry).

    Args:
        contours_location_element: XML-элемент <contours_location>
                                    (после strip namespaces). Может быть None.

    Returns:
        Dict[geom_type, QgsGeometry]: ключи "MultiPolygonM" / "MultiLineStringM" /
        "MultiPointM" или {"NoGeometry": None} если данных нет.
        Для публичного сервитута ожидается "MultiPolygonM".
    """
    return extract_geometry(contours_location_element)


def get_primary_geometry(geometries_dict: Dict[str, QgsGeometry]) -> Optional[QgsGeometry]:
    """
    Выбрать основную геометрию из результата extract_geometry.

    Приоритет: полигон -> линия -> точка. Для публичного сервитута
    практически всегда возвращается MultiPolygonM.

    Args:
        geometries_dict: словарь геометрий по типам

    Returns:
        QgsGeometry или None если геометрия отсутствует
    """
    if not geometries_dict or "NoGeometry" in geometries_dict:
        return None

    if "MultiPolygonM" in geometries_dict:
        return geometries_dict["MultiPolygonM"]
    if "MultiLineStringM" in geometries_dict:
        return geometries_dict["MultiLineStringM"]
    if "MultiPointM" in geometries_dict:
        return geometries_dict["MultiPointM"]

    return None
