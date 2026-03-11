# -*- coding: utf-8 -*-
"""
Msm_28_2_CuttingSchemaProvider - Провайдер схемы полей нарезки

Загружает структуру 27 полей для слоёв Le_2_1_* и Le_2_2_* из Base_cutting.json
через Msm_4_12 (LayerFieldStructureManager) и предоставляет их
в формате, совместимом с M_28_LayerSchemaValidator.

Зависимости:
- Msm_4_12 (LayerFieldStructureManager) - источник данных из API
- Msm_28_1 (ForestVydelySchemaProvider) - переиспользование _parse_mapinfo_format
"""

from typing import List, Dict, Any, Optional

from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_error


class CuttingSchemaProvider:
    """Провайдер схемы полей для слоёв нарезки (Le_2_1_*, Le_2_2_*)

    Загружает 27 обязательных полей из Base_cutting.json через API,
    парсит mapinfo_format в QMetaType.Type + length.
    """

    def __init__(self) -> None:
        self._cached_fields: Optional[List[Dict[str, Any]]] = None

    def get_required_fields(self) -> List[Dict[str, Any]]:
        """Получить список обязательных полей с типами.

        Returns:
            [{"name": "ID", "type": QMetaType.Type.Int, "length": 0},
             {"name": "Услов_КН", "type": QMetaType.Type.QString, "length": 254},
             ...]
        """
        if self._cached_fields is not None:
            return self._cached_fields

        fields = self._load_from_api()
        if fields:
            self._cached_fields = fields
            return fields

        log_error("Msm_28_2: API недоступен, Base_cutting.json не загружен")
        return []

    def get_field_names(self) -> List[str]:
        """Получить список имён обязательных полей."""
        return [f["name"] for f in self.get_required_fields()]

    def _load_from_api(self) -> Optional[List[Dict[str, Any]]]:
        """Загрузить поля из Base_cutting.json через Msm_4_12.

        Returns:
            Список полей с типами или None при ошибке
        """
        try:
            from Daman_QGIS.managers import LayerFieldStructureManager
            from Daman_QGIS.managers.validation.submodules.Msm_28_1_forest_vydely_schema import (
                ForestVydelySchemaProvider,
            )

            manager = LayerFieldStructureManager()
            raw_fields = manager.get_cutting_fields()

            if not raw_fields:
                log_error("Msm_28_2: Base_cutting.json вернул пустой список")
                return None

            result: List[Dict[str, Any]] = []
            for field_data in raw_fields:
                working_name = field_data.get("working_name", "")
                mapinfo_format = field_data.get("mapinfo_format", "")

                if not working_name:
                    continue

                field_type, field_length = ForestVydelySchemaProvider._parse_mapinfo_format(
                    mapinfo_format
                )
                result.append({
                    "name": working_name,
                    "type": field_type,
                    "length": field_length,
                })

            log_info(f"Msm_28_2: Загружено {len(result)} полей из API")
            return result

        except Exception as e:
            log_error(f"Msm_28_2: Ошибка загрузки из API: {e}")
            return None
