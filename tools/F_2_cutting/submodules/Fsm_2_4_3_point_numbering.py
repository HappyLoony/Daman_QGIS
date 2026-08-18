# -*- coding: utf-8 -*-
"""
Fsm_2_4_3_PointNumbering - Единая нумерация характерных точек этапности

НАЗНАЧЕНИЕ:
    Один проход M_20 по merged-списку контуров (этап 1 + этап 2): единое
    пространство номеров, общие координаты наследуют номер. Перед нумерацией
    выполняется нормализация колец M_47 (pass-1), после — поле "Точки"
    раздаётся по ссылке в те же словари.

ОСОБЕННОСТИ:
    - Порядок нумерации — по возрастанию ID контуров (sort_northwest=False).
    - Регион 78: per-ring режим (каждое кольцо с 1) по региональному нормативу.
    - Менеджер нумерации передаётся снаружи: повторный вызов на том же менеджере
      сбросил бы счётчик и разрушил единое пространство.

ИСПОЛЬЗОВАНИЕ:
    Вызывается F_2_4_Staging ровно один раз на прогон.
"""

from typing import Any, Dict, List, Tuple, TYPE_CHECKING

from Daman_QGIS.constants import POINTS_FIELD_NONE
from Daman_QGIS.managers import registry
from Daman_QGIS.utils import log_info, log_error

if TYPE_CHECKING:
    from Daman_QGIS.managers import PointNumberingManager


class Fsm_2_4_3_PointNumbering:
    """Единая нумерация характерных точек слоёв этапности"""

    def number_points(
        self,
        features_data: List[Dict[str, Any]],
        point_numbering: 'PointNumberingManager'
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Единая нумерация точек merged-списка и обновление поля 'Точки'

        Вызывается ОДИН раз на тип слоя для merged-списка (stage1 + stage2):
        единое пространство номеров — контуры обоих этапов нумеруются по
        возрастанию ID (интерливинг), общие координаты наследуют номер.

        Нумерация по возрастанию ID контуров (sort_northwest=False) —
        осознанное расхождение с СЗ-порядком эталона F_2_1/M_26: там ID
        присвоены по СЗ и порядки совпадают, в F_2_4 ID приходят из ЗПР.

        Поле 'Точки' раздаётся ПО ССЫЛКЕ (M_20 мутирует те же dict'ы) —
        НЕ индексным сопоставлением списков (исторический корень
        100%-перестановки поля при NW-пересортировке внутри M_20).

        Args:
            features_data: merged-список объектов с 'geometry' и 'attributes'
            point_numbering: менеджер нумерации (прокидывается caller'ом —
                            заготовка для будущей сквозной нумерации Раздел→НГС)

        Returns:
            Tuple: (features_data с заполненным полем 'Точки', points_data)
        """
        if not features_data:
            return features_data, []

        # Подготавливаем данные для PointNumberingManager
        # Нужны поля: 'geometry', 'contour_id', 'attributes'
        for item in features_data:
            if 'contour_id' not in item:
                contour_id = item['attributes'].get('ID')
                if contour_id is None:
                    # Подстановка 0 склеила бы все безымянные контуры в один
                    # ключ нумерации — точки разъехались бы молча
                    raise RuntimeError(
                        "Fsm_2_4_3: контур без ID — нумерация точек невозможна"
                    )
                item['contour_id'] = contour_id

        # Детерминированный порядок нумерации: по возрастанию ID контуров.
        # Сортировка непосредственно перед M_20 (контракт менеджеров ВРИ/Вид_Работ
        # порядок не гарантирует, даже если фактически они мутируют in-place).
        features_data.sort(key=lambda x: x['attributes'].get('ID', 0))

        # M_47 pass-1 (level-map two-pass): normalize_geometry на merged ДО M_20.
        # F_2_4 mixed-level — M_20 строит «Точки» из features_data здесь; pass-1 держит
        # «Точки» и .gpkg vertex-order согласованными. Pass-2 (normalize_layer на .gpkg
        # после OGR-записи) — в caller _create_staging_layer, страхует OGR ring-reorder.
        from Daman_QGIS.managers.geometry import PolygonNormalizationManager
        for item in features_data:
            _ng = PolygonNormalizationManager.normalize_geometry(item.get('geometry'))
            if _ng is None:
                # Молчаливый пропуск оставлял бы порядок вершин в файле
                # рассогласованным с номерами точек в атрибуте
                log_error(
                    f"Fsm_2_4_3: M_47 отверг геометрию контура "
                    f"ID={item['attributes'].get('ID')} — нумерация точек невозможна"
                )
                raise RuntimeError("Fsm_2_4_3: нормализация геометрии отказала")
            item['geometry'] = _ng

        # Нумерация точек
        # Регион 78 (СПб): per-ring нумерация (каждое кольцо с 1)
        regional_mgr = registry.get('M_44')
        per_ring = regional_mgr.is_region('78') if regional_mgr else False

        _, points_data = point_numbering.process_polygon_layer(
            features_data, precision=2,
            sort_northwest=False,
            per_ring_numbering=per_ring
        )

        # Обновление поля "Точки" по ссылке: M_20 пишет point_numbers_str
        # в те же dict'ы — иммунитет к любому изменению порядка списка
        missing_numbers = []
        for item in features_data:
            numbers = item.get('point_numbers_str')
            if numbers:
                item['attributes']['Точки'] = numbers
            else:
                # Пустой результат нумерации — дефект, а не «нет данных»:
                # прочерк в этом поле неотличим от штатного пропуска (Без_Меж)
                missing_numbers.append(item['attributes'].get('ID'))
                item['attributes']['Точки'] = POINTS_FIELD_NONE

        if missing_numbers:
            log_error(
                f"Fsm_2_4_3: нумерация не дала точек для контуров "
                f"{sorted(str(i) for i in missing_numbers)}"
            )
            raise RuntimeError("Fsm_2_4_3: нумерация точек дала пустой результат")

        log_info(f"Fsm_2_4_3: Нумерация точек завершена, обновлено {len(features_data)} объектов")
        return features_data, points_data
