# -*- coding: utf-8 -*-
"""
Fsm_2_4_10_Stage2Builder - Данные 2 этапа этапности (объединение по ЗПР)

НАЗНАЧЕНИЕ:
    Объединяет контуры 1 этапа, отнесённые к одному контуру ЗПР, в один объект
    2 этапа: сливает геометрию, собирает состав контуров, переносит атрибуты и
    определяет кадастровый квартал и адрес объединённого контура.

ОСОБЕННОСТИ:
    - Контур без пары по ЗПР во 2 этап не идёт.
    - Геометрия объединения снапится к сетке COORDINATE_PRECISION.

ИСПОЛЬЗОВАНИЕ:
    Вызывается F_2_4_Staging после формирования 1 этапа.
"""

from typing import Any, Dict, List, Optional, Tuple

from qgis.core import QgsGeometry, QgsVectorLayer

from Daman_QGIS.constants import COORDINATE_PRECISION
from Daman_QGIS.managers.geometry.submodules.Msm_26_2_attribute_mapper import Msm_26_2_AttributeMapper
from Daman_QGIS.utils import log_info, log_warning, log_error

from .Fsm_2_1_5_kk_matcher import Fsm_2_1_5_KKMatcher
from .Fsm_2_4_8_geocoder import Fsm_2_4_8_Geocoder


class Fsm_2_4_10_Stage2Builder:
    """Сборка данных 2 этапа этапности"""

    def __init__(
        self,
        attribute_mapper: Msm_26_2_AttributeMapper,
        kk_matcher: Optional[Fsm_2_1_5_KKMatcher],
        geocoder: Fsm_2_4_8_Geocoder,
        oks_zu_manager
    ) -> None:
        """Инициализация

        Args:
            attribute_mapper: Маппер атрибутов объединяемых контуров (Msm_26_2)
            kk_matcher: Сопоставление с кадастровыми кварталами (Fsm_2_1_5)
            geocoder: Определение адреса объединённого контура (Fsm_2_4_8)
            oks_zu_manager: Менеджер связи ОКС и ЗУ
        """
        self._attribute_mapper = attribute_mapper
        self._kk_matcher = kk_matcher
        self._geocoder = geocoder
        self._oks_zu_manager = oks_zu_manager

    def prepare_stage2_data(
        self,
        source_layer: QgsVectorLayer,
        feature_zpr_mapping: Dict[int, int],
        features_by_zpr: Dict[int, List[int]],
        merging_features: set,
        stage1_data: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Dict[int, str]]:
        """Подготовка данных для 2 этапа (объединение)

        Объединяет участки с одинаковым zpr_id в один контур.
        Добавляет поле "Состав_контуров" с перечислением ID из 1 этапа (100, 101...).
        КН и Услов_КН присваиваются по логике НГС - привязка к КК (не к ЗУ),
        так как на момент 2 этапа ещё неизвестно какой номер ЗУ будет присвоен.

        Args:
            stage1_data: Данные 1 этапа для получения правильных ID

        Returns:
            Tuple:
                - stage2_data: список объединённых контуров
                - merged_contours_info: {zpr_id: "100;101;102"}
        """
        if not merging_features:
            return [], {}

        # Счётчик условных КН сбрасывается на каждый слой, а контуры 1 этапа
        # уже заняли номера в тех же кварталах: без посева 2 этап начал бы ряд
        # `:ЗУ1` заново и выдал бы занятые номера
        self._attribute_mapper.seed_kn_counter(
            item.get('attributes', {}).get('Услов_КН') for item in stage1_data
        )

        stage2_data = []
        merged_contours_info: Dict[int, str] = {}

        # Создаём маппинг original_fid → данные из stage1_data
        # ВАЖНО: Используем stage1_data вместо source_layer.getFeature()
        # потому что feature.id() в QGIS может быть нестабильным для GPKG слоёв
        fid_to_stage1_item: Dict[int, Dict] = {}
        for item in stage1_data:
            original_fid = item.get('original_fid')
            if original_fid is not None:
                fid_to_stage1_item[original_fid] = item

        # Группируем по zpr_id для объединения
        groups_with_multiple = [(zpr_id, len(fids)) for zpr_id, fids in features_by_zpr.items() if len(fids) > 1]
        log_info(f"Fsm_2_4_10: Групп для объединения (2 этап): {len(groups_with_multiple)}")

        for zpr_id, feature_ids in features_by_zpr.items():
            if len(feature_ids) <= 1:
                continue  # Не требует объединения

            # Собираем геометрии для объединения из stage1_data
            geometries = []
            stage1_ids = []  # ID из 1 этапа (100, 101...)
            sample_attrs = None

            for fid in feature_ids:
                # Используем данные из stage1_data вместо source_layer.getFeature()
                stage1_item = fid_to_stage1_item.get(fid)
                if not stage1_item:
                    log_warning(f"Fsm_2_4_10: zpr_id={zpr_id}, fid={fid} - не найден в stage1_data")
                    continue

                geom = stage1_item.get('geometry')
                if not geom or geom.isEmpty():
                    log_warning(f"Fsm_2_4_10: zpr_id={zpr_id}, fid={fid} - геометрия пустая")
                    continue

                geometries.append(QgsGeometry(geom))
                # Берём ID из 1 этапа (100, 101...)
                stage1_id = stage1_item['attributes'].get('ID', fid)
                stage1_ids.append(str(stage1_id))

                attrs = stage1_item.get('attributes', {})
                if sample_attrs is None:
                    sample_attrs = dict(attrs)

            # Члены группы уже помечены временными и в Итог не попадут, поэтому
            # пропуск группы = дыра в покрытии ЗПР. Дыру ловит сборщик Итога
            # сверкой множеств (Fsm_2_4_9).
            if not geometries or len(geometries) < 2:
                log_error(
                    f"Fsm_2_4_10: группа ЗПР {zpr_id} не объединена: "
                    f"геометрий {len(geometries)}, контуров {len(feature_ids)}"
                )
                continue

            # Объединяем геометрии
            merged_geom = QgsGeometry.unaryUnion(geometries)
            # Округляем координаты до стандартной точности после объединения
            merged_geom = merged_geom.snappedToGrid(COORDINATE_PRECISION, COORDINATE_PRECISION)

            if merged_geom.isEmpty():
                log_error(
                    f"Fsm_2_4_10: объединение контуров ЗПР {zpr_id} дало пустую "
                    f"геометрию, состав: {sorted(stage1_ids)}"
                )
                continue

            # Формируем строку состава контуров (ID из 1 этапа: 100, 101...)
            contours_str = ", ".join(sorted(stage1_ids, key=lambda x: int(x) if x.isdigit() else 0))
            merged_contours_info[zpr_id] = contours_str

            # Атрибуты для объединённого контура
            # Во 2 этапе - как НГС: привязка к КК, без информации о сущ. ЗУ
            # Поля исходных ЗУ (Категория, ВРИ, Площадь и т.д.) должны быть пустыми,
            # так как контуры ещё не существуют - получат КН только после 1 этапа.
            # Санитайзер в конце заменит пустые/NULL значения на "-".
            attrs = dict(sample_attrs) if sample_attrs else {}
            attrs['ID'] = zpr_id  # ID = ID контура ЗПР

            # Очищаем поля исходных ЗУ - на 2 этапе они неизвестны
            # (исключения: План_категория, План_ВРИ, Площадь_ОЗУ - их мы знаем)
            #
            # Поля наложений (реестр M_26.OVERLAY_CONFIG) очищаются по той же
            # причине: sample_attrs взяты у произвольного члена группы, а
            # наложения определяются объединённой геометрией. Прочерк честнее
            # значения соседнего контура. Пересчёт по merged_geom требует
            # overlay-слоёв, которых домен tools не видит — отдельная задача.
            fields_to_clear = [
                'Тип_объекта', 'Категория', 'ВРИ', 'Площадь',
                'Права', 'Обременения', 'Собственники', 'Арендаторы',
                'НП', 'ООПТ', 'МО', 'Лес', 'Вода'
            ]
            for field_name in fields_to_clear:
                if field_name in attrs:
                    attrs[field_name] = None  # Будет заменено на "-" санитайзером

            # Адрес для 2 этапа -- геокодирование по центроиду через M_39
            attrs['Адрес_Местоположения'] = self._geocoder.geocode_address(
                merged_geom, source_layer.crs()
            )

            # Привязка к КК (как НГС) - используем KKMatcher с проверкой нулёвок
            # КН = номер кадастрового квартала
            # Услов_КН = КН:ЗУ{N} (как для НГС)
            kk_kn = None
            if self._kk_matcher:
                kk_kn = self._kk_matcher.find_quarter_for_geometry(merged_geom)

            if kk_kn:
                # Валидный квартал найден (не нулёвка)
                attrs['КН'] = kk_kn
                # Генерируем Услов_КН через AttributeMapper (счётчик для каждого КН)
                attrs['Услов_КН'] = self._attribute_mapper.generate_conditional_kn(kk_kn)
            else:
                # Квартал не найден или нулёвка
                attrs['КН'] = "-"
                attrs['Услов_КН'] = "-"

            # Пересчёт площади (целое число как в Base_cutting.json)
            attrs['Площадь_ОЗУ'] = int(round(merged_geom.area()))

            # Пересчёт ОКС_на_ЗУ для 2 этапа через M_23:
            # - выписка = "-" (КН неизвестен, как НГС)
            # - факт = ПЕРЕСЧИТАТЬ геометрически для объединённой геометрии
            # Менеджер связи ОКС и ЗУ обязателен по контракту конструктора:
            # охрана здесь маскировала бы нарушение контракта тихим fallback
            # source_kn = None означает логику НГС (выписка не используется)
            oks_values = self._oks_zu_manager.analyze_cutting_geometry(
                geometry=merged_geom,
                source_kn=None  # Как НГС - выписка = "-"
            )
            attrs['ОКС_на_ЗУ_выписка'] = oks_values.get('ОКС_на_ЗУ_выписка', '-')
            attrs['ОКС_на_ЗУ_факт'] = oks_values.get('ОКС_на_ЗУ_факт', '-')

            stage2_data.append({
                'geometry': merged_geom,
                'attributes': attrs,
                'zpr_id': zpr_id,
                'merged_contours': contours_str
            })

        # Сортировка по ID (zpr_id)
        stage2_data.sort(key=lambda x: x['attributes'].get('ID', 0))

        return stage2_data, merged_contours_info
