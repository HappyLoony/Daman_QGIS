# -*- coding: utf-8 -*-
"""Fsm_5_3_9_1 — Сбор данных по 7 подразделам пояснительной записки (регион 78).

Источники:
- T1, T2, T5, T7 — 14 ZU-слоёв (Раздел W=1 + НГС W=2 × 7 категорий)
- T3 — слои выписок Le_1_6_2_* (обратный индекс по Связанные_ЗУ)
- T4 — 7 ПС-слоёв (W=4)
- T6 — те же ЗУ что T5, без строки S= (DocBuilder выводит через show_area=False)

PyQGIS-импорты выполняются отложенно (внутри методов), чтобы файл можно было
загружать в окружении без QGIS (например, в юнит-тестах метаданных).
"""
import re
from typing import Optional, Dict, Any, List, Tuple

from Daman_QGIS.utils import log_info, log_warning, log_error


MODULE_ID = 'Fsm_5_3_9_1'


class ExplanatoryNoteDataCollector:
    """Сбор данных T1-T7 из слоёв проекта."""

    # 14 слоёв нарезки: 7 категорий × {Раздел W=1, НГС W=2}
    ZU_LAYER_NAMES: Tuple[str, ...] = (
        'Le_2_1_1_1_Раздел_ЗПР_ОКС', 'Le_2_1_1_2_НГС_ЗПР_ОКС',
        'Le_2_1_2_1_Раздел_ЗПР_ПО', 'Le_2_1_2_2_НГС_ЗПР_ПО',
        'Le_2_1_3_1_Раздел_ЗПР_ВО', 'Le_2_1_3_2_НГС_ЗПР_ВО',
        'Le_2_2_1_1_Раздел_ЗПР_РЕК_АД', 'Le_2_2_1_2_НГС_ЗПР_РЕК_АД',
        'Le_2_2_2_1_Раздел_ЗПР_СЕТИ_ПО', 'Le_2_2_2_2_НГС_ЗПР_СЕТИ_ПО',
        'Le_2_2_3_1_Раздел_ЗПР_СЕТИ_ВО', 'Le_2_2_3_2_НГС_ЗПР_СЕТИ_ВО',
        'Le_2_2_4_1_Раздел_ЗПР_НЭ', 'Le_2_2_4_2_НГС_ЗПР_НЭ',
    )

    # 7 ПС-слоёв (W=4) — для T4 «Сервитуты»
    PS_LAYER_NAMES: Tuple[str, ...] = (
        'Le_2_1_1_4_ПС_ЗПР_ОКС',
        'Le_2_1_2_4_ПС_ЗПР_ПО',
        'Le_2_1_3_4_ПС_ЗПР_ВО',
        'Le_2_2_1_4_ПС_ЗПР_РЕК_АД',
        'Le_2_2_2_4_ПС_ЗПР_СЕТИ_ПО',
        'Le_2_2_3_4_ПС_ЗПР_СЕТИ_ВО',
        'Le_2_2_4_4_ПС_ЗПР_НЭ',
    )

    # T6 = T5 без строки S= (DocBuilder выводит show_area=False).
    # Раздел концептуально называется «Сведения о границах территории ПМТ»,
    # но фактически содержит те же ЗУ что в T5, только без площадей. ГПМТ
    # как отдельный слой (M_35) не используется.

    # Слои выписок ОН — для T3 «Объекты недвижимости»
    OKS_LAYER_NAMES: Tuple[str, ...] = (
        'Le_1_6_2_1_Выписки_ОКС_line',
        'Le_1_6_2_2_Выписки_ОКС_poly',
        'Le_1_6_2_3_Выписки_ОКС_not',
    )

    # Маркер слоя «без координат границ» (для T3)
    OKS_NOT_LAYER_MARKER = '_not'

    # Имена merged-Excel из Region78FormatModifier (Msm_37_1).
    # Экспортёр Fsm_5_3_1 убирает ведущее подчёркивание при сохранении,
    # поэтому проверяем оба варианта.
    MERGED_ZU_EXCEL_CANDIDATES = (
        'Перечень_координат_ЗУ.xlsx',
        '_Перечень_координат_ЗУ.xlsx',
    )
    MERGED_ZU_SUBFOLDER = 'Земельные участки'

    def __init__(self, iface, ref_managers=None, export_folder=None):
        """
        Args:
            iface: интерфейс QGIS.
            ref_managers: reference managers.
            export_folder: корневая папка экспорта (для парсинга merged Excel
                перечней координат — ускорение T5/T6 через переиспользование
                уже сформированных Fsm_5_3_1 файлов).
        """
        self.iface = iface
        self.ref_managers = ref_managers
        self.export_folder = export_folder

    @staticmethod
    def _safe_progress(callback, msg: str, percent: int) -> None:
        """Безопасный вызов progress_callback (None / ошибка не блокируют сбор)."""
        if callback is None:
            return
        try:
            callback(msg, percent)
        except Exception as e:
            log_warning(f"{MODULE_ID} (_safe_progress): callback error {e}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _find_layer(name: str):
        """Найти слой по имени.

        Отсутствие слоя — нормальная ситуация (например, в проекте есть только
        ПО-категория из 7 возможных), warning не выводится.
        Невалидный слой — патология, warning сохраняется.

        Returns:
            QgsVectorLayer или None.
        """
        from qgis.core import QgsProject, QgsVectorLayer

        layers = QgsProject.instance().mapLayersByName(name)
        for lyr in layers:
            if isinstance(lyr, QgsVectorLayer):
                if not lyr.isValid():
                    log_warning(f"{MODULE_ID} (_find_layer): слой '{name}' невалиден")
                    return None
                return lyr
        return None

    @staticmethod
    def _attr(feature, name: str):
        """Безопасное чтение атрибута. Возвращает None если поле отсутствует или NULL."""
        try:
            idx = feature.fields().indexOf(name)
            if idx < 0:
                return None
            value = feature.attribute(name)
        except Exception:
            return None
        # NULL-объект QVariant конвертируется PyQGIS в None автоматически.
        if value is None:
            return None
        # На некоторых сборках NULL приходит как QVariant; страхуемся через str.
        try:
            from qgis.PyQt.QtCore import QVariant  # noqa: F401
            if isinstance(value, QVariant) and value.isNull():
                return None
        except Exception:
            pass
        return value

    @staticmethod
    def _to_float(value):
        """Преобразовать значение в float, поддерживая русскую запятую как разделитель.

        Атрибуты слоёв нарезки могут приходить String с запятой (источник —
        MapInfo / TAB-импорт). float('1008,50') падает → нормализуем в '1008.50'.
        Возвращает None при невозможности конвертации.
        """
        if value is None or value == '':
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            try:
                # Replace последнюю запятую на точку (на случай тысячных «1 008,50»)
                s = str(value).strip().replace(' ', '').replace(',', '.')
                return float(s)
            except (ValueError, TypeError):
                return None

    @staticmethod
    def _format_ha(sqm) -> str:
        """кв.м → га (4 знака, запятая). Пусто/ошибка → '-'."""
        v = ExplanatoryNoteDataCollector._to_float(sqm)
        if v is None:
            return '-'
        return f"{v / 10000:.4f}".replace('.', ',')

    @staticmethod
    def _format_sqm(sqm) -> str:
        """кв.м → целое (для строки S=)."""
        v = ExplanatoryNoteDataCollector._to_float(sqm)
        if v is None:
            return '0'
        return str(int(round(v)))

    @staticmethod
    def _format_coord(value) -> str:
        """Координата → строка с 2 знаками, запятая. None/ошибка → '-'."""
        v = ExplanatoryNoteDataCollector._to_float(value)
        if v is None:
            return '-'
        return f"{v:.2f}".replace('.', ',')

    @staticmethod
    def _is_yes(value) -> bool:
        """Boolean-в-строке: 'Да'/'yes'/'true'/'1' → True."""
        if value is None:
            return False
        return str(value).strip().lower() in ('да', 'yes', 'true', '1')

    @staticmethod
    def _reservation_label(reservation: bool, izm: bool) -> str:
        """Комбинированная подпись «Резервирование/Изъятие»."""
        if reservation and izm:
            return 'Резервирование и изъятие'
        if reservation:
            return 'Резервирование'
        if izm:
            return 'Изъятие'
        return ''

    @staticmethod
    def _is_ngs_layer(layer_name: str) -> bool:
        """W=2 (НГС) — кадастровый номер исходного ЗУ отсутствует."""
        return '_НГС_' in layer_name

    @staticmethod
    def _str_or_dash(value) -> str:
        """Строка или '-' для пустых значений."""
        if value is None:
            return '-'
        s = str(value).strip()
        return s if s else '-'

    # ------------------------------------------------------------------
    # T1 — Перечень образуемых ЗУ
    # ------------------------------------------------------------------
    def _collect_t1_zu_rows(self) -> List[Dict[str, Any]]:
        """T1: все features из 14 ZU-слоёв.

        Колонки:
            id, points, kn ('-' для НГС), area_ha, common_land,
            work_kind, category, source_layer
        """
        rows: List[Dict[str, Any]] = []
        for layer_name in self.ZU_LAYER_NAMES:
            layer = self._find_layer(layer_name)
            if layer is None:
                continue
            is_ngs = self._is_ngs_layer(layer_name)
            try:
                for feat in layer.getFeatures():
                    kn_raw = self._attr(feat, 'КН')
                    rows.append({
                        'id': self._str_or_dash(self._attr(feat, 'ID')),
                        'points': self._str_or_dash(self._attr(feat, 'Точки')),
                        'kn': '-' if is_ngs else self._str_or_dash(kn_raw),
                        'area_ha': self._format_ha(self._attr(feat, 'Площадь_ОЗУ')),
                        'common_land': self._str_or_dash(self._attr(feat, 'Общая_земля')),
                        'work_kind': self._str_or_dash(self._attr(feat, 'Вид_Работ')),
                        'category': self._str_or_dash(self._attr(feat, 'План_категория')),
                        'source_layer': layer_name,
                    })
            except Exception as exc:
                log_error(f"{MODULE_ID} (_collect_t1_zu_rows): ошибка чтения '{layer_name}': {exc}")
        log_info(f"{MODULE_ID} (_collect_t1_zu_rows): собрано {len(rows)} строк")
        return rows

    # ------------------------------------------------------------------
    # T2 — Резервирование / Изъятие
    # ------------------------------------------------------------------
    def _collect_t2_reservation_rows(self) -> List[Dict[str, Any]]:
        """T2: ZU-features где Резервирование == 'Да' OR Изъятие == 'Да'.

        Колонки: id, kn_existing, address, reservation_kind
        """
        rows: List[Dict[str, Any]] = []
        for layer_name in self.ZU_LAYER_NAMES:
            layer = self._find_layer(layer_name)
            if layer is None:
                continue
            try:
                for feat in layer.getFeatures():
                    reservation = self._is_yes(self._attr(feat, 'Резервирование'))
                    izm = self._is_yes(self._attr(feat, 'Изъятие'))
                    if not (reservation or izm):
                        continue
                    rows.append({
                        'id': self._str_or_dash(self._attr(feat, 'ID')),
                        'kn_existing': self._str_or_dash(self._attr(feat, 'КН')),
                        'address': self._str_or_dash(self._attr(feat, 'Адрес_Местоположения')),
                        'reservation_kind': self._reservation_label(reservation, izm),
                    })
            except Exception as exc:
                log_error(
                    f"{MODULE_ID} (_collect_t2_reservation_rows): "
                    f"ошибка чтения '{layer_name}': {exc}"
                )
        log_info(f"{MODULE_ID} (_collect_t2_reservation_rows): собрано {len(rows)} строк")
        return rows

    # ------------------------------------------------------------------
    # T3 — Объекты недвижимости (обратный индекс по Связанные_ЗУ)
    # ------------------------------------------------------------------
    def _collect_t3_realty_rows(self, kn_list: List[str]) -> List[Dict[str, Any]]:
        """T3: ОН из Le_1_6_2_*, чьи Связанные_ЗУ пересекаются с kn_list.

        Колонки: kn_zu, kn_oks (с суффиксом '(без координат границ)' для _not),
                 address, name
        """
        rows: List[Dict[str, Any]] = []
        if not kn_list:
            log_info(f"{MODULE_ID} (_collect_t3_realty_rows): kn_list пуст, пропуск")
            return rows
        kn_set = {str(k).strip() for k in kn_list if k and str(k).strip()}
        if not kn_set:
            return rows

        for layer_name in self.OKS_LAYER_NAMES:
            layer = self._find_layer(layer_name)
            if layer is None:
                continue
            no_coords = self.OKS_NOT_LAYER_MARKER in layer_name
            try:
                for feat in layer.getFeatures():
                    related_raw = self._attr(feat, 'Связанные_ЗУ')
                    if not related_raw:
                        continue
                    related_list = [
                        kn.strip() for kn in str(related_raw).split(';') if kn.strip()
                    ]
                    matched = [kn for kn in related_list if kn in kn_set]
                    if not matched:
                        continue
                    kn_oks_raw = self._str_or_dash(self._attr(feat, 'КН'))
                    kn_oks = (
                        f"{kn_oks_raw} (без координат границ)"
                        if no_coords and kn_oks_raw != '-'
                        else kn_oks_raw
                    )
                    address = self._str_or_dash(self._attr(feat, 'Адрес_Местоположения'))
                    name = self._str_or_dash(self._attr(feat, 'Наименование'))
                    for kn_zu in matched:
                        rows.append({
                            'kn_zu': kn_zu,
                            'kn_oks': kn_oks,
                            'address': address,
                            'name': name,
                        })
            except Exception as exc:
                log_error(
                    f"{MODULE_ID} (_collect_t3_realty_rows): "
                    f"ошибка чтения '{layer_name}': {exc}"
                )
        log_info(f"{MODULE_ID} (_collect_t3_realty_rows): собрано {len(rows)} строк")
        return rows

    # ------------------------------------------------------------------
    # T4 — Сервитуты
    # ------------------------------------------------------------------
    def _collect_t4_servitude_rows(self) -> List[Dict[str, Any]]:
        """T4: все features из 7 ПС-слоёв.

        Колонки: num (счётчик), kn_existing, address
        """
        rows: List[Dict[str, Any]] = []
        counter = 0
        for layer_name in self.PS_LAYER_NAMES:
            layer = self._find_layer(layer_name)
            if layer is None:
                continue
            try:
                for feat in layer.getFeatures():
                    counter += 1
                    rows.append({
                        'num': counter,
                        'kn_existing': self._str_or_dash(self._attr(feat, 'КН')),
                        'address': self._str_or_dash(
                            self._attr(feat, 'Адрес_Местоположения')
                        ),
                    })
            except Exception as exc:
                log_error(
                    f"{MODULE_ID} (_collect_t4_servitude_rows): "
                    f"ошибка чтения '{layer_name}': {exc}"
                )
        log_info(f"{MODULE_ID} (_collect_t4_servitude_rows): собрано {len(rows)} строк")
        return rows

    # ------------------------------------------------------------------
    # T5 — Координаты ЗУ (с площадью)
    # ------------------------------------------------------------------
    def _find_points_layer(self, layer_name: str):
        """Найти Т_*-слой для слоя нарезки.

        Логика идентична Fsm_5_3_1._find_points_layer (Le_2_1_X_Y → Le_2_5_X_Y _Т_,
        Le_2_2_X_Y → Le_2_6_X_Y _Т_).
        TODO Phase 4.6: вынести в общий хелпер вместе с Fsm_5_3_1, чтобы избежать
        дублирования.
        """
        from qgis.core import Qgis, QgsProject, QgsVectorLayer

        match_cutting = re.match(r'^(Le_2_)([12])(_\d+_\d+_)(.+)$', layer_name)
        if not match_cutting:
            log_warning(
                f"{MODULE_ID} (_find_points_layer): паттерн нарезки не сработал для "
                f"'{layer_name}'"
            )
            return None
        group_map = {'1': '5', '2': '6'}
        new_group = group_map.get(match_cutting.group(2), match_cutting.group(2))
        points_layer_name = (
            f"{match_cutting.group(1)}{new_group}{match_cutting.group(3)}"
            f"Т_{match_cutting.group(4)}"
        )
        for lyr in QgsProject.instance().mapLayers().values():
            if (
                isinstance(lyr, QgsVectorLayer)
                and lyr.name() == points_layer_name
                and lyr.geometryType() == Qgis.GeometryType.Point
            ):
                return lyr
        # Отсутствие Т_*-слоя — норма (если у feature нет нумерации точек,
        # координаты возьмутся напрямую из геометрии). Без warning.
        return None

    @staticmethod
    def _round_key(x: float, y: float, precision: int = 2) -> Tuple[float, float]:
        return (round(float(x), precision), round(float(y), precision))

    def _build_points_index(self, points_layer) -> Dict[Tuple[float, float], Dict[str, Any]]:
        """Индекс точек: (x_round, y_round) → {num, x, y}.

        Берёт первое непустое поле из ('Номер_точки', 'Номер', 'N', 'point_num', 'Num').
        """
        idx: Dict[Tuple[float, float], Dict[str, Any]] = {}
        if points_layer is None:
            return idx
        candidate_fields = ('Номер_точки', 'Номер', 'N', 'point_num', 'Num', 'ID')
        try:
            field_names = [f.name() for f in points_layer.fields()]
        except Exception:
            field_names = []
        num_field = next((f for f in candidate_fields if f in field_names), None)
        try:
            for feat in points_layer.getFeatures():
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue
                pt = geom.asPoint() if not geom.isMultipart() else None
                if pt is None:
                    # MultiPoint — берём первую точку
                    multi = geom.asMultiPoint()
                    if not multi:
                        continue
                    pt = multi[0]
                num = self._attr(feat, num_field) if num_field else None
                key = self._round_key(pt.x(), pt.y())
                idx[key] = {
                    'num': str(num) if num is not None else '-',
                    'x': pt.x(),
                    'y': pt.y(),
                }
        except Exception as exc:
            log_warning(
                f"{MODULE_ID} (_build_points_index): ошибка построения индекса "
                f"'{points_layer.name()}': {exc}"
            )
        return idx

    def _extract_polygon_rings(self, geom) -> List[Dict[str, Any]]:
        """Извлечь кольца полигона/мультиполигона раздельно: exterior + holes.

        Для каждого polygon в MultiPolygon: ring[0] — exterior, ring[1..] — holes
        (per OGC SFA / GDAL). Возвращает список {is_hole, vertices}, в порядке
        обхода (exterior, hole_1, hole_2, ..., exterior_2, ...).

        Используется в fallback-сборе T5 (когда merged Excel отсутствует) для
        корректной отрисовки подзаголовка «Внутренний контур N» в DOCX.
        """
        rings: List[Dict[str, Any]] = []
        if geom is None or geom.isEmpty():
            return rings
        try:
            if geom.isMultipart():
                polygons = geom.asMultiPolygon()
            else:
                polygons = [geom.asPolygon()]
            for poly in polygons:
                for ring_idx, ring in enumerate(poly):
                    vertices = [(pt.x(), pt.y()) for pt in ring]
                    rings.append({
                        'is_hole': ring_idx > 0,
                        'vertices': vertices,
                    })
        except Exception as exc:
            log_warning(
                f"{MODULE_ID} (_extract_polygon_rings): ошибка извлечения колец: {exc}"
            )
        return rings

    def _parse_merged_zu_excel(self, path: str) -> List[Dict[str, Any]]:
        """Парсить merged Excel перечня координат ЗУ (формируется Fsm_5_3_1).

        Формат файла (Fsm_5_3_1._export_merged_layer):
            Row 0: заголовок документа (длинный текст, b/c=None)
            Row 1: «Номер точки | Х (м) | Y (м)» — шапка
            Row 2: 1 | 2 | 3 — нумерация колонок
            Row N: «Образуемый земельный участок {K}» (merge A:C) — заголовок группы
            Row N+1..: K | X | Y — точки внешнего контура (нумерация с 1)
            [Row]: «Внутренний контур M» (merge A:C) — разделитель отверстия
            [Row+1..]: K | X | Y — точки внутреннего контура (нумерация с 1)
            ... повтор для следующих holes
            Row последний: «S=NNN кв. м» (только col 0) — площадь группы
            ... повтор для следующих групп

        Возвращает: list[{title, rings: [{subtitle, points}], area_sqm}].
        Первый ring — exterior (subtitle=None), последующие — holes с subtitle
        «Внутренний контур N».
        """
        try:
            import openpyxl
        except ImportError:
            log_warning(f"{MODULE_ID} (_parse_merged_zu_excel): openpyxl недоступен")
            return []

        groups: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None
        current_ring: Optional[Dict[str, Any]] = None
        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            for row in ws.iter_rows(values_only=True):
                a = row[0] if len(row) > 0 else None
                b = row[1] if len(row) > 1 else None
                c = row[2] if len(row) > 2 else None
                if a is None and b is None and c is None:
                    continue
                # Заголовок группы: 'Образуемый ...' в col0, b и c пустые
                if isinstance(a, str) and b is None and c is None and 'Образуемый' in a:
                    if current is not None:
                        groups.append(current)
                    current_ring = {'subtitle': None, 'points': []}
                    current = {
                        'title': a.strip(),
                        'rings': [current_ring],
                        'area_sqm': '0',
                    }
                    continue
                # Подзаголовок внутреннего контура: 'Внутренний контур N'
                if (isinstance(a, str) and b is None and c is None
                        and 'Внутренний контур' in a):
                    if current is not None:
                        current_ring = {'subtitle': a.strip(), 'points': []}
                        current['rings'].append(current_ring)
                    continue
                # «S=NNN кв. м»
                if isinstance(a, str) and b is None and c is None and a.startswith('S='):
                    if current is not None:
                        area = (a.replace('S=', '')
                                  .replace('кв. м', '').replace('кв.м', '')
                                  .strip())
                        current['area_sqm'] = area
                    continue
                # Точка: a — int/float (номер), b/c — float (X/Y)
                if (isinstance(a, (int, float)) and isinstance(b, (int, float))
                        and isinstance(c, (int, float))):
                    if current_ring is not None:
                        try:
                            num_str = str(int(a))
                        except (ValueError, TypeError):
                            num_str = str(a)
                        current_ring['points'].append({
                            'point_num': num_str,
                            'x': self._format_coord(b),
                            'y': self._format_coord(c),
                        })
                    continue
                # Шапка / нумерация колонок / прочее — пропуск
            if current is not None:
                groups.append(current)
            wb.close()
        except Exception as exc:
            log_warning(
                f"{MODULE_ID} (_parse_merged_zu_excel): "
                f"ошибка парсинга '{path}': {exc}"
            )
            return []
        return groups

    def _try_load_merged_zu_excel(self) -> Optional[List[Dict[str, Any]]]:
        """Найти и распарсить merged Excel перечня координат ЗУ.

        Если export_folder не задан или файла нет — None (fallback на сбор
        через слои нарезки).
        """
        if not self.export_folder:
            return None
        import os as _os
        zu_folder = _os.path.join(self.export_folder, self.MERGED_ZU_SUBFOLDER)
        if not _os.path.isdir(zu_folder):
            return None
        for name in self.MERGED_ZU_EXCEL_CANDIDATES:
            path = _os.path.join(zu_folder, name)
            if _os.path.isfile(path):
                groups = self._parse_merged_zu_excel(path)
                if groups:
                    log_info(
                        f"{MODULE_ID} (_try_load_merged_zu_excel): "
                        f"использован Excel '{name}': {len(groups)} групп"
                    )
                    return groups
                return None
        return None

    @staticmethod
    def _sort_groups_by_id(groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Отсортировать группы координат по числовому ID из title.

        Title формат: 'Образуемый земельный участок {ID}'. Источник ЗУ (Раздел
        W=1 / НГС W=2) не имеет значения — важна сквозная нумерация. Например,
        НГС=1,2,3,10,11 + Раздел=4..9 → итог 1,2,3,4,5,6,7,8,9,10,11.

        Поддерживает составные ID ('5.1' → (5, 1)). Title без чисел уходит в
        конец списка. Stable sort сохраняет исходный порядок при равных ключах.
        """
        def _key(g):
            title = g.get('title') or ''
            nums = re.findall(r'\d+', title)
            if not nums:
                return (float('inf'),)
            return tuple(int(n) for n in nums)
        return sorted(groups, key=_key)

    def _collect_t5_zu_coordinates(self) -> List[Dict[str, Any]]:
        """T5: координаты вершин для каждого ZU (группами).

        Каждая группа:
            title: «Образуемый земельный участок {ID}»
            points: list[{point_num, x, y}]
            area_sqm: целое (для строки S=)

        Приоритет 1: переиспользовать готовый merged Excel '_Перечень_координат_ЗУ.xlsx'
        (формируется Fsm_5_3_1 ранее в этом же экспорте). Это даёт корректную
        нумерацию точек и кратно ускоряет сбор T5/T6 (391 ЗУ → ~50ms vs 30+s).
        Приоритет 2 (fallback): сбор через слои нарезки + Т_*-индекс точек.
        """
        excel_groups = self._try_load_merged_zu_excel()
        if excel_groups is not None:
            return excel_groups

        # Fallback: сбор через слои нарезки
        groups: List[Dict[str, Any]] = []
        for layer_name in self.ZU_LAYER_NAMES:
            layer = self._find_layer(layer_name)
            if layer is None:
                continue
            points_layer = self._find_points_layer(layer_name)
            points_index = self._build_points_index(points_layer)
            try:
                for feat in layer.getFeatures():
                    feat_id = self._str_or_dash(self._attr(feat, 'ID'))
                    area_sqm = self._format_sqm(self._attr(feat, 'Площадь_ОЗУ'))
                    geom = feat.geometry()
                    raw_rings = self._extract_polygon_rings(geom)
                    rings_out: List[Dict[str, Any]] = []
                    hole_counter = 0
                    for ring in raw_rings:
                        is_hole = ring.get('is_hole', False)
                        seen_keys = set()
                        points_out: List[Dict[str, Any]] = []
                        for x, y in ring.get('vertices', []):
                            key = self._round_key(x, y)
                            if key in seen_keys:
                                continue
                            seen_keys.add(key)
                            info = points_index.get(key)
                            points_out.append({
                                'point_num': info['num'] if info else '-',
                                'x': self._format_coord(info['x'] if info else x),
                                'y': self._format_coord(info['y'] if info else y),
                            })
                        if not points_out:
                            continue
                        if is_hole:
                            hole_counter += 1
                            subtitle = f"Внутренний контур {hole_counter}"
                        else:
                            subtitle = None
                        rings_out.append({'subtitle': subtitle, 'points': points_out})
                    if not rings_out:
                        rings_out = [{'subtitle': None, 'points': []}]
                    groups.append({
                        'title': f"Образуемый земельный участок {feat_id}",
                        'rings': rings_out,
                        'area_sqm': area_sqm,
                    })
            except Exception as exc:
                log_error(
                    f"{MODULE_ID} (_collect_t5_zu_coordinates): "
                    f"ошибка чтения '{layer_name}': {exc}"
                )
        log_info(f"{MODULE_ID} (_collect_t5_zu_coordinates): собрано {len(groups)} групп ЗУ")
        return groups

    # ------------------------------------------------------------------
    # T7 — ВРИ
    # ------------------------------------------------------------------
    def _collect_t7_vri_rows(self) -> List[Dict[str, Any]]:
        """T7: ВРИ образуемых ЗУ.

        Колонки: num (счётчик), id_zu, vri (План_ВРИ или '-').
        """
        rows: List[Dict[str, Any]] = []
        counter = 0
        for layer_name in self.ZU_LAYER_NAMES:
            layer = self._find_layer(layer_name)
            if layer is None:
                continue
            try:
                for feat in layer.getFeatures():
                    counter += 1
                    rows.append({
                        'num': counter,
                        'id_zu': self._str_or_dash(self._attr(feat, 'ID')),
                        'vri': self._str_or_dash(self._attr(feat, 'План_ВРИ')),
                    })
            except Exception as exc:
                log_error(
                    f"{MODULE_ID} (_collect_t7_vri_rows): "
                    f"ошибка чтения '{layer_name}': {exc}"
                )
        log_info(f"{MODULE_ID} (_collect_t7_vri_rows): собрано {len(rows)} строк")
        return rows

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------
    def collect_all(self, progress_callback=None) -> Dict[str, Any]:
        """Собрать данные всех 7 таблиц.

        Args:
            progress_callback: callable(msg: str, percent: int) — опц.,
                для обновления прогресс-бара в F_5_3.

        Returns:
            {'t1_zu': [...], 't2_reservation': [...], 't3_realty': [...],
             't4_servitude': [...], 't5_coords': [...], 't6_gpmt_coords': [...],
             't7_vri': [...]}
        """
        log_info(f"{MODULE_ID} (collect_all): начало сбора данных T1-T7")
        cb = progress_callback

        # Прогресс распределён 10..70% (60% общего на сбор данных)
        self._safe_progress(cb, 'T1: образуемые ЗУ (14 слоёв)', 12)
        t1 = self._collect_t1_zu_rows()

        self._safe_progress(cb, 'T2: резервирование/изъятие', 22)
        t2 = self._collect_t2_reservation_rows()

        # T3 нужен kn_list из T2 (исходные ЗУ для резервирования/изъятия).
        kn_list = [
            row.get('kn_existing')
            for row in t2
            if row.get('kn_existing') and row.get('kn_existing') != '-'
        ]
        self._safe_progress(cb, f'T3: объекты недвижимости ({len(kn_list)} ЗУ)', 32)
        t3 = self._collect_t3_realty_rows(kn_list)

        self._safe_progress(cb, 'T4: сервитуты (7 ПС-слоёв)', 42)
        t4 = self._collect_t4_servitude_rows()

        self._safe_progress(cb, 'T5: координаты ЗУ', 50)
        t5 = self._collect_t5_zu_coordinates()
        # Сквозная нумерация ЗУ независимо от источника (Раздел / НГС): merged
        # Excel и слои нарезки идут блоками W=1 → W=2, но в T5/T6 ID должны
        # быть упорядочены по числу.
        t5 = self._sort_groups_by_id(t5)

        # T6 = T5 без строки S= (DocBuilder вызывает _build_coords_table со
        # show_area=False). Концептуально раздел про «границы территории ПМТ»,
        # но фактически содержит те же ЗУ что в T5.
        self._safe_progress(cb, 'T6: те же координаты ЗУ без площадей', 60)
        t6 = list(t5)

        self._safe_progress(cb, 'T7: ВРИ образуемых ЗУ', 67)
        t7 = self._collect_t7_vri_rows()

        result = {
            't1_zu': t1,
            't2_reservation': t2,
            't3_realty': t3,
            't4_servitude': t4,
            't5_coords': t5,
            't6_gpmt_coords': t6,
            't7_vri': t7,
        }
        log_info(
            f"{MODULE_ID} (collect_all): готово — "
            f"T1={len(t1)} T2={len(t2)} T3={len(t3)} T4={len(t4)} "
            f"T5={len(t5)} T6={len(t6)} T7={len(t7)}"
        )
        return result
