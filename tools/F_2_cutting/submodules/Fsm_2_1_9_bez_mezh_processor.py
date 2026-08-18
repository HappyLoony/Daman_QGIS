# -*- coding: utf-8 -*-
"""
Fsm_2_1_9_BezMezhProcessor - Процессор создания features для Без_Меж ЗУ

НАЗНАЧЕНИЕ:
    Создание features_data для ЗУ Без_Меж на основе результатов детекции.
    Features сохраняют исходную геометрию ЗУ и копируют атрибуты.

ОСОБЕННОСТИ:
    - Геометрия = исходная геометрия ЗУ (не нарезается)
    - Услов_КН = КН (сохраняется кадастровый номер)
    - План_ВРИ = ВРИ (из ЗУ, не меняется)
    - План_категория = Категория (из ЗУ, не меняется)
    - Вид_Работ = "Существующий (сохраняемый) земельный участок"
    - Точки = "-" (нет нумерации)

ИСПОЛЬЗОВАНИЕ:
    Вызывается в Msm_26_4_CuttingEngine после детекции.
"""

from typing import Dict, List, Tuple, Optional, Any

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
)

from Daman_QGIS.utils import log_info, log_warning, log_error, sort_by_northwest
from Daman_QGIS.constants import WORK_TYPE_BEZ_MEZH, POINTS_FIELD_NONE

# Типы для аннотаций
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from Daman_QGIS.managers.geometry.submodules.Msm_26_2_attribute_mapper import Msm_26_2_AttributeMapper


class Fsm_2_1_9_BezMezhProcessor:
    """
    Процессор создания features для Без_Меж ЗУ

    Создаёт features_data в формате совместимом с layer_creator,
    но сохраняя исходную геометрию ЗУ.
    """

    def __init__(
        self,
        zu_layer: QgsVectorLayer,
        zpr_layer: QgsVectorLayer,
        attribute_mapper: 'Msm_26_2_AttributeMapper'
    ):
        """
        Инициализация процессора

        Args:
            zu_layer: Слой Выборка_ЗУ
            zpr_layer: Слой ЗПР
            attribute_mapper: Маппер атрибутов для генерации полей
        """
        self.zu_layer = zu_layer
        self.zpr_layer = zpr_layer
        self.attribute_mapper = attribute_mapper

        # Кэш features для быстрого доступа по fid
        self._zu_features: Dict[int, QgsFeature] = {}
        self._zpr_features: Dict[int, QgsFeature] = {}

        self._build_feature_cache()

    def _build_feature_cache(self):
        """Построение кэша features"""
        for feature in self.zu_layer.getFeatures():
            self._zu_features[feature.id()] = QgsFeature(feature)

        for feature in self.zpr_layer.getFeatures():
            self._zpr_features[feature.id()] = QgsFeature(feature)

        log_info(f"Fsm_2_1_9: Кэш построен (ЗУ: {len(self._zu_features)}, "
                f"ЗПР: {len(self._zpr_features)})")

    def create_features(
        self,
        bez_mezh_zu_with_zpr: List[Tuple[int, int]],
        layer_name: str,
        zpr_type: str
    ) -> List[Dict[str, Any]]:
        """
        Создать features_data для Без_Меж ЗУ

        Args:
            bez_mezh_zu_with_zpr: Список пар (zu_fid, zpr_fid) из детектора
            layer_name: Имя целевого слоя
            zpr_type: Тип ЗПР (ОКС, ЛО, ВО)

        Returns:
            Список features_data в формате для layer_creator
        """
        features_data = []

        for zu_fid, zpr_fid in bez_mezh_zu_with_zpr:
            zu_feature = self._zu_features.get(zu_fid)
            zpr_feature = self._zpr_features.get(zpr_fid)

            if not zu_feature:
                log_warning(f"Fsm_2_1_9: ЗУ fid={zu_fid} не найден в кэше")
                continue

            if not zpr_feature:
                log_warning(f"Fsm_2_1_9: ЗПР fid={zpr_fid} не найден в кэше")
                continue

            # Создаём feature_data
            feature_data = self._create_single_feature(
                zu_feature, zpr_feature, layer_name, zpr_type
            )

            if feature_data:
                features_data.append(feature_data)

        # Сортировка от СЗ к ЮВ для корректной нумерации ID
        features_data = sort_by_northwest(features_data)

        # Переназначение ID после сортировки (1, 2, 3... в порядке СЗ -> ЮВ)
        for idx, feat in enumerate(features_data, start=1):
            feat['attributes']['ID'] = idx

        log_info(f"Fsm_2_1_9: Создано {len(features_data)} Без_Меж features")
        return features_data

    def _create_single_feature(
        self,
        zu_feature: QgsFeature,
        zpr_feature: QgsFeature,
        layer_name: str,
        zpr_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Создать feature_data для одного ЗУ

        Args:
            zu_feature: Feature ЗУ
            zpr_feature: Feature ЗПР в которую попадает ЗУ
            layer_name: Имя целевого слоя
            zpr_type: Тип ЗПР

        Returns:
            Dict с geometry, attributes, zpr_vri или None при ошибке
        """
        zu_geom = zu_feature.geometry()

        if not zu_geom or zu_geom.isEmpty():
            log_warning(f"Fsm_2_1_9: ЗУ fid={zu_feature.id()} имеет пустую геометрию")
            return None

        # Маппинг атрибутов из ЗУ
        zu_attrs = self.attribute_mapper.map_zu_attributes(zu_feature)

        # Генерация расчётных полей (ID, Площадь и т.д.)
        attributes = self.attribute_mapper.fill_generated_fields(
            zu_attrs, zu_geom, layer_name, zpr_type
        )

        # Переопределяем специфичные для Без_Меж атрибуты
        attributes = self._override_bez_mezh_attributes(attributes, zu_attrs)

        # Получаем zpr_vri для совместимости с форматом
        zpr_vri = None
        for field_name in ['ВРИ', 'VRI', 'vri']:
            if field_name in zpr_feature.fields().names():
                zpr_vri = zpr_feature[field_name]
                break

        return {
            'geometry': QgsGeometry(zu_geom),  # Копия исходной геометрии
            'attributes': attributes,
            'zpr_vri': zpr_vri
        }

    def _override_bez_mezh_attributes(
        self,
        attributes: Dict[str, Any],
        zu_attrs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Переопределить атрибуты специфичные для Без_Меж

        Args:
            attributes: Базовые атрибуты
            zu_attrs: Атрибуты из ЗУ

        Returns:
            Обновлённые атрибуты
        """
        # Услов_КН = КН (сохраняем оригинальный кадастровый номер)
        kn = zu_attrs.get('КН', '-')
        attributes['Услов_КН'] = kn if kn else '-'

        # План_ВРИ = ВРИ из ЗУ (не меняется, БЕЗ нормализации)
        # ВАЖНО: Для Без_Меж берём ТОЧНУЮ копию ВРИ из исходного ЗУ
        vri = zu_attrs.get('ВРИ', '-')
        plan_vri = vri if vri else '-'
        attributes['План_ВРИ'] = plan_vri
        log_info(f"Fsm_2_1_9: План_ВРИ установлен = '{plan_vri}' (из ВРИ='{vri}')")

        # План_категория = Категория из ЗУ (не меняется, БЕЗ нормализации)
        # ВАЖНО: Для Без_Меж берём ТОЧНУЮ копию Категории из исходного ЗУ
        category = zu_attrs.get('Категория', '-')
        plan_category = category if category else '-'
        attributes['План_категория'] = plan_category
        log_info(f"Fsm_2_1_9: План_категория установлена = '{plan_category}'")

        # Общая_земля - определяется по ВРИ из исходного ЗУ
        # Правило «Общая_земля» живёт в M_21 — единственном доме
        from Daman_QGIS.managers.validation.M_21_vri_assignment_manager import (
            VRIAssignmentManager,
        )
        attributes['Общая_земля'] = (
            VRIAssignmentManager.get_instance().public_territory_by_vri(vri)
        )

        # Площадь_ОЗУ НЕ перезаписывается полем «Площадь» из ЗУ: то поле
        # символьное и при отсутствии сведений ЕГРН содержит «-», из-за чего
        # ниже по конвейеру площадь читалась как 0 и ЗУ переезжал из Без_Меж
        # в Изм с фиктивной «реестровой ошибкой». Значение уже посчитано по
        # геометрии в fill_generated_fields (Msm_26_2).

        # Вид_Работ - константа для Без_Меж
        attributes['Вид_Работ'] = WORK_TYPE_BEZ_MEZH

        # Точки = "-" (нет нумерации для Без_Меж)
        attributes['Точки'] = POINTS_FIELD_NONE

        return attributes


