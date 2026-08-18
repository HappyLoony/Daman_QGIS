# -*- coding: utf-8 -*-
"""
Fsm_2_1_8_IzmenyaemyeProcessor - Процессор создания features для Изменяемых ЗУ

НАЗНАЧЕНИЕ:
    Создание features_data для Изменяемых ЗУ на основе результатов детекции.
    Features сохраняют исходную геометрию ЗУ и копируют атрибуты.

ОСОБЕННОСТИ:
    - Геометрия = исходная геометрия ЗУ (не нарезается)
    - Услов_КН = КН (сохраняется кадастровый номер)
    - План_ВРИ = ВРИ или из ЗПР (через Msm_21_1_ExistingVRIValidator)
    - План_категория = Категория или из ЗПР (через M_36)
    - Вид_Работ = "Изменение характеристик земельного участка"
    - Точки = "-" (нет нумерации)

ИСПОЛЬЗОВАНИЕ:
    Вызывается в Msm_26_4_CuttingEngine после детекции Изменяемых.
"""

from typing import Dict, List, Tuple, Optional, Any

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
)

from Daman_QGIS.utils import log_info, log_warning, log_error, sort_by_northwest
from Daman_QGIS.constants import WORK_TYPE_IZM, POINTS_FIELD_NONE

# Типы для аннотаций
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from Daman_QGIS.managers.geometry.submodules.Msm_26_2_attribute_mapper import Msm_26_2_AttributeMapper


class Fsm_2_1_8_IzmenyaemyeProcessor:
    """
    Процессор создания features для Изменяемых ЗУ

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

        # Кэш features для быстрого доступа
        self._zu_features: Dict[int, QgsFeature] = {}
        self._zpr_features: Dict[int, QgsFeature] = {}

        self._build_feature_cache()

    def _build_feature_cache(self):
        """Построение кэша features"""
        for feature in self.zu_layer.getFeatures():
            self._zu_features[feature.id()] = QgsFeature(feature)

        for feature in self.zpr_layer.getFeatures():
            self._zpr_features[feature.id()] = QgsFeature(feature)

        log_info(f"Fsm_2_1_8: Кэш построен - "
                f"{len(self._zu_features)} ЗУ, {len(self._zpr_features)} ЗПР")

    def create_features(
        self,
        izm_zu_with_zpr: List[Tuple[int, int]],
        layer_name: str,
        zpr_type: str
    ) -> List[Dict[str, Any]]:
        """
        Создать features_data для Изменяемых ЗУ

        Args:
            izm_zu_with_zpr: Список кортежей (zu_fid, zpr_fid)
            layer_name: Имя целевого слоя Изм
            zpr_type: Тип ЗПР (ОКС, ЛО, ВО)

        Returns:
            List[Dict]: features_data в формате для layer_creator:
                - 'geometry': QgsGeometry (исходная геометрия ЗУ)
                - 'attributes': dict (атрибуты)
                - 'zpr_vri': str (ВРИ из ЗПР для валидации)
        """
        result = []

        for zu_fid, zpr_fid in izm_zu_with_zpr:
            zu_feature = self._zu_features.get(zu_fid)
            zpr_feature = self._zpr_features.get(zpr_fid)

            if not zu_feature:
                log_warning(f"Fsm_2_1_8: ЗУ fid={zu_fid} не найден в кэше")
                continue

            zu_geom = zu_feature.geometry()
            if not zu_geom or zu_geom.isEmpty():
                log_warning(f"Fsm_2_1_8: ЗУ fid={zu_fid} имеет пустую геометрию")
                continue

            # Извлекаем ВРИ из ЗПР для валидации
            zpr_vri = None
            if zpr_feature:
                for vri_field in ['ВРИ', 'VRI', 'vri']:
                    if vri_field in zpr_feature.fields().names():
                        zpr_vri = zpr_feature[vri_field]
                        break

            # Маппинг атрибутов из ЗУ
            zu_attrs = self.attribute_mapper.map_zu_attributes(zu_feature)

            # Генерация расчётных полей (используем существующий метод)
            # Но переопределяем специфичные для Изм поля
            attributes = self.attribute_mapper.fill_generated_fields(
                zu_attrs, zu_geom, layer_name, zpr_type
            )

            # Переопределение атрибутов для Изменяемых
            attributes = self._override_izm_attributes(attributes, zu_attrs, zpr_vri)

            result.append({
                'geometry': QgsGeometry(zu_geom),  # Копия исходной геометрии
                'attributes': attributes,
                'zpr_vri': zpr_vri  # Для валидации через Msm_21_1
            })

        # Сортировка от СЗ к ЮВ для корректной нумерации ID
        result = sort_by_northwest(result)

        # Переназначение ID после сортировки (1, 2, 3... в порядке СЗ -> ЮВ)
        for idx, feat in enumerate(result, start=1):
            feat['attributes']['ID'] = idx

        log_info(f"Fsm_2_1_8: Создано {len(result)} features для Изменяемых")
        return result

    def _override_izm_attributes(
        self,
        attributes: Dict[str, Any],
        zu_attrs: Dict[str, Any],
        zpr_vri: Optional[str]
    ) -> Dict[str, Any]:
        """
        Переопределить атрибуты специфичные для Изменяемых

        Args:
            attributes: Сгенерированные атрибуты
            zu_attrs: Исходные атрибуты ЗУ
            zpr_vri: ВРИ из ЗПР

        Returns:
            Обновлённые атрибуты
        """
        # Услов_КН = КН (сохраняем оригинальный КН)
        kn = zu_attrs.get('КН', '-')
        if kn and kn != '-':
            attributes['Услов_КН'] = kn
        else:
            attributes['Услов_КН'] = '-'

        # План_ВРИ = ВРИ из ЗПР (строгий, "причёсанный")
        # Изменяемые = ЗУ где ВРИ не совпадает с ЗПР, поэтому берём ВРИ из ЗПР
        attributes['План_ВРИ'] = zpr_vri if zpr_vri else '-'

        # План_категория - fallback из ЗУ, будет переназначена через M_36
        # в Msm_26_4 (шаг 3.3) по пространственному пересечению с НП/ООПТ/Лес
        category = zu_attrs.get('Категория', '-')
        attributes['План_категория'] = category if category else '-'

        # Площадь_ОЗУ НЕ перезаписывается полем «Площадь» из ЗУ: то поле
        # символьное и при отсутствии сведений ЕГРН содержит «-», из-за чего
        # ниже по конвейеру площадь читалась как 0 и ЗУ получал фиктивную
        # «реестровую ошибку площади». Значение уже посчитано по геометрии
        # в fill_generated_fields (Msm_26_2).

        # Вид_Работ - константа для Изменяемых
        attributes['Вид_Работ'] = WORK_TYPE_IZM

        # Точки = "-" (нет нумерации для Изменяемых)
        attributes['Точки'] = POINTS_FIELD_NONE

        return attributes

