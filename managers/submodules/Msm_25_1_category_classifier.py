# -*- coding: utf-8 -*-
"""
Msm_25_1 - Классификатор категорий земель

Определяет в какой слой L_2_2_* должен попасть объект
на основе значения поля "Категория".

Маппинг загружается из Base_layers.json (group='Категории_ЗУ').

Перенесено из Fsm_2_3_1_land_categories.py
"""

from typing import Dict, Tuple, Optional

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers import get_reference_managers


class Msm_25_1_CategoryClassifier:
    """Классификатор категорий земель"""

    # Слой по умолчанию для неизвестных категорий
    DEFAULT_LAYER = "L_2_2_8_КАТ_Не_установлена"

    def __init__(self):
        """Инициализация классификатора"""
        self._category_mapping: Optional[Dict[Optional[str], Tuple[str, str]]] = None

    def get_category_mapping(self) -> Dict[Optional[str], Tuple[str, str]]:
        """
        Получить маппинг категорий из Base_layers.json

        Returns:
            Dict[category_name, (full_name, short_name)]:
                category_name: Значение поля "Категория" (или None для пустых)
                full_name: Полное имя слоя (L_2_2_1_КАТ_Земли_НП)
                short_name: Короткое имя (КАТ_Земли_НП)
        """
        if self._category_mapping is not None:
            return self._category_mapping

        ref_managers = get_reference_managers()
        layer_ref_manager = ref_managers.layer

        if not layer_ref_manager:
            log_error("Msm_25_1: Не удалось получить layer reference manager")
            return {}

        mapping: Dict[Optional[str], Tuple[str, str]] = {}
        all_layers = layer_ref_manager.get_base_layers()

        for layer_data in all_layers:
            group = layer_data.get('group', '')
            if group == 'Категории_ЗУ':
                full_name = layer_data.get('full_name', '')
                description = layer_data.get('description', '')

                if full_name:
                    short_name = layer_data.get('layer', '')

                    # Маппинг по description
                    if 'Земли населённых пунктов' in description or 'Земли населенных пунктов' in description:
                        mapping['Земли населённых пунктов'] = (full_name, short_name)
                        mapping['Земли населенных пунктов'] = (full_name, short_name)
                    elif 'Земли сельскохозяйственного назначения' in description:
                        mapping['Земли сельскохозяйственного назначения'] = (full_name, short_name)
                    elif 'промышленности' in description:
                        # Полное название категории
                        mapping['Земли промышленности, энергетики, транспорта, связи, радиовещания, телевидения, информатики, земли для обеспечения космической деятельности, земли обороны, безопасности и земли иного специального назначения'] = (full_name, short_name)
                    elif 'особо охраняемых территорий' in description:
                        mapping['Земли особо охраняемых территорий и объектов'] = (full_name, short_name)
                    elif 'лесного фонда' in description:
                        mapping['Земли лесного фонда'] = (full_name, short_name)
                    elif 'водного фонда' in description:
                        mapping['Земли водного фонда'] = (full_name, short_name)
                    elif 'запаса' in description:
                        mapping['Земли запаса'] = (full_name, short_name)
                    elif 'Категория не установлена' in description or 'не установлена' in description:
                        mapping['Категория не установлена'] = (full_name, short_name)
                        mapping[None] = (full_name, short_name)  # Для пустых значений

        self._category_mapping = mapping
        log_info(f"Msm_25_1: Загружен маппинг для {len(mapping)} категорий")

        return mapping

    def classify_feature(self, category_value: Optional[str]) -> str:
        """
        Определить целевой слой по значению категории

        Args:
            category_value: Значение поля "Категория"

        Returns:
            str: Имя целевого слоя (full_name)
        """
        mapping = self.get_category_mapping()

        # Нормализуем значение
        if category_value is None:
            normalized_value = ""
        else:
            normalized_value = str(category_value).strip()

        # Проверяем на пустое значение
        if not normalized_value or normalized_value == "-":
            target = mapping.get(None)
            if target:
                return target[0]
            return self.DEFAULT_LAYER

        # Ищем точное совпадение
        target = mapping.get(normalized_value)
        if target:
            return target[0]

        # Ищем частичное совпадение (категория содержит ключ)
        for key, value in mapping.items():
            if key is not None and key in normalized_value:
                return value[0]

        # Ищем частичное совпадение (ключ содержит категорию)
        for key, value in mapping.items():
            if key is not None and normalized_value in key:
                return value[0]

        # Не найдено - возвращаем слой по умолчанию
        log_warning(f"Msm_25_1: Неизвестная категория '{normalized_value}' -> {self.DEFAULT_LAYER}")
        return self.DEFAULT_LAYER

    def get_field_name(self) -> str:
        """
        Получить имя поля для классификации

        Returns:
            str: Имя поля ("Категория")
        """
        return "Категория"
