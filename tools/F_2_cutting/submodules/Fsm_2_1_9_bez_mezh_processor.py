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

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.constants import WORK_TYPE_BEZ_MEZH

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
        features_data = self._sort_by_northwest(features_data)

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

        # Услов_ЕЗ = ЕЗ (единое землепользование)
        ez = zu_attrs.get('ЕЗ', '-')
        attributes['Услов_ЕЗ'] = ez if ez else '-'

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
        attributes['Общая_земля'] = self._determine_public_territory(vri)

        # Площадь_ОЗУ = Площадь (из ЗУ, не пересчитывается)
        area = zu_attrs.get('Площадь', 0)
        if area:
            attributes['Площадь_ОЗУ'] = area

        # Вид_Работ - константа для Без_Меж
        attributes['Вид_Работ'] = WORK_TYPE_BEZ_MEZH

        # Точки = "-" (нет нумерации для Без_Меж)
        attributes['Точки'] = '-'

        return attributes

    def _determine_public_territory(self, vri_value: Optional[str]) -> str:
        """Определить значение поля Общая_земля по ВРИ

        Использует M_21 (VRIAssignmentManager) Singleton с force_reload=True
        для гарантированного использования актуального кода.
        Поддерживает поиск по name (короткое имя) и full_name (полное имя с кодом).
        Поддерживает множественные ВРИ через разделитель ",".

        Args:
            vri_value: Значение ВРИ из исходного ЗУ (может быть множественным)

        Returns:
            "Отнесен" если хотя бы один ВРИ относится к территории общего пользования,
            "Не отнесен" в противном случае
        """
        if not vri_value or vri_value == '-':
            log_info(f"Fsm_2_1_9: ВРИ пустой или '-', Общая_земля = 'Не отнесен'")
            return "Не отнесен"

        try:
            from Daman_QGIS.managers.validation.M_21_vri_assignment_manager import VRIAssignmentManager

            vri_manager = VRIAssignmentManager.get_instance()

            # Разбиваем множественные ВРИ по запятой
            vri_parts = [v.strip() for v in vri_value.split(',') if v.strip()]
            log_info(f"Fsm_2_1_9: Проверка Общая_земля для ВРИ '{vri_value}' (частей: {len(vri_parts)})")

            for vri_str in vri_parts:
                # Используем метод менеджера для получения данных ВРИ
                vri_data = vri_manager._get_vri_data_for_single(vri_str)
                if vri_data:
                    is_public = vri_data.get('is_public_territory', False)
                    log_info(f"Fsm_2_1_9: ВРИ '{vri_str}' найден, is_public_territory={is_public}")
                    if is_public:
                        log_info(f"Fsm_2_1_9: ВРИ '{vri_str}' относится к территории общего пользования -> 'Отнесен'")
                        return VRIAssignmentManager.PUBLIC_TERRITORY_YES
                else:
                    log_warning(f"Fsm_2_1_9: ВРИ '{vri_str}' НЕ найден в базе VRI.json")

            log_info(f"Fsm_2_1_9: Ни один ВРИ не относится к территории общего пользования -> 'Не отнесен'")
            return VRIAssignmentManager.PUBLIC_TERRITORY_NO

        except Exception as e:
            log_warning(f"Fsm_2_1_9: Ошибка определения Общая_земля: {e}")
            return "Не отнесен"

    def get_bez_mezh_layer_name(self, zpr_type: str) -> str:
        """
        Получить имя слоя Без_Меж для типа ЗПР

        Args:
            zpr_type: Тип ЗПР (ОКС, ЛО, ВО)

        Returns:
            Имя слоя Без_Меж
        """
        from Daman_QGIS.constants import (
            LAYER_CUTTING_OKS_BEZ_MEZH,
            LAYER_CUTTING_PO_BEZ_MEZH,
            LAYER_CUTTING_VO_BEZ_MEZH,
        )

        layer_map = {
            'ОКС': LAYER_CUTTING_OKS_BEZ_MEZH,
            'ЛО': LAYER_CUTTING_PO_BEZ_MEZH,
            'ВО': LAYER_CUTTING_VO_BEZ_MEZH,
        }

        return layer_map.get(zpr_type, LAYER_CUTTING_OKS_BEZ_MEZH)

    @staticmethod
    def _sort_by_northwest(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Сортировка features от СЗ к ЮВ

        Обеспечивает назначение ID контуров в порядке от северо-западного
        к юго-восточному (по расстоянию центроида до СЗ угла глобального MBR).

        Args:
            data: Список features_data (каждый элемент содержит 'geometry')

        Returns:
            Отсортированный список
        """
        if len(data) <= 1:
            return data

        # Глобальный MBR
        global_min_x = float('inf')
        global_max_y = float('-inf')
        centroids = []

        for item in data:
            geom = item['geometry']
            if geom and not geom.isEmpty():
                centroid = geom.centroid().asPoint()
                centroids.append((centroid.x(), centroid.y()))
                bbox = geom.boundingBox()
                global_min_x = min(global_min_x, bbox.xMinimum())
                global_max_y = max(global_max_y, bbox.yMaximum())
            else:
                centroids.append(None)

        nw_x, nw_y = global_min_x, global_max_y

        def sort_key(idx_item):
            idx, _ = idx_item
            c = centroids[idx]
            if c is None:
                return float('inf')
            return (c[0] - nw_x) ** 2 + (c[1] - nw_y) ** 2

        indexed = list(enumerate(data))
        indexed.sort(key=sort_key)
        return [item for _, item in indexed]
