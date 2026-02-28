# -*- coding: utf-8 -*-
"""
Msm_28_1_ForestVydelySchemaProvider - Провайдер схемы полей лесных выделов

Загружает структуру полей для Le_3_1_1_1_Лес_Ред_Выделы из Base_forest_vydely.json
через Msm_4_12 (LayerFieldStructureManager) и предоставляет их
в формате, совместимом с M_28_LayerSchemaValidator.

Ключевое отличие от ZPR: поля имеют разные типы (Int, String с разной длиной),
а не единый String(254).

Зависимости:
- Msm_4_12 (LayerFieldStructureManager) - источник данных из API
- QMetaType.Type - типы полей QGIS
"""

import re
from typing import List, Dict, Any, Tuple, Optional

from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_error


class ForestVydelySchemaProvider:
    """Провайдер схемы полей для Le_3_1_1_1_Лес_Ред_Выделы

    Загружает 17 обязательных полей из Base_forest_vydely.json через API,
    парсит mapinfo_format в QMetaType.Type + length.
    """

    def __init__(self) -> None:
        self._cached_fields: Optional[List[Dict[str, Any]]] = None

    def get_required_fields(self) -> List[Dict[str, Any]]:
        """Получить список обязательных полей с типами.

        Returns:
            [{"name": "Лесничество", "type": QMetaType.Type.QString, "length": 254},
             {"name": "Номер_квартала", "type": QMetaType.Type.Int, "length": 0},
             ...]

        Raises:
            RuntimeError: Если API недоступен и данные не загружены
        """
        if self._cached_fields is not None:
            return self._cached_fields

        fields = self._load_from_api()
        if fields:
            self._cached_fields = fields
            return fields

        log_error("Msm_28_1: API недоступен, Base_forest_vydely.json не загружен")
        return []

    def get_field_names(self) -> List[str]:
        """Получить список имён обязательных полей."""
        return [f["name"] for f in self.get_required_fields()]

    def _load_from_api(self) -> Optional[List[Dict[str, Any]]]:
        """Загрузить поля из Base_forest_vydely.json через Msm_4_12.

        Returns:
            Список полей с типами или None при ошибке
        """
        try:
            from Daman_QGIS.managers import LayerFieldStructureManager

            manager = LayerFieldStructureManager()
            raw_fields = manager.get_forest_vydely_fields()

            if not raw_fields:
                log_error("Msm_28_1: Base_forest_vydely.json вернул пустой список")
                return None

            result: List[Dict[str, Any]] = []
            for field_data in raw_fields:
                working_name = field_data.get("working_name", "")
                mapinfo_format = field_data.get("mapinfo_format", "")

                if not working_name:
                    continue

                field_type, field_length = self._parse_mapinfo_format(mapinfo_format)
                result.append({
                    "name": working_name,
                    "type": field_type,
                    "length": field_length,
                })

            log_info(f"Msm_28_1: Загружено {len(result)} полей из API")
            return result

        except Exception as e:
            log_error(f"Msm_28_1: Ошибка загрузки из API: {e}")
            return None

    @staticmethod
    def _parse_mapinfo_format(mapinfo_format: str) -> Tuple[QMetaType.Type, int]:
        """Парсинг mapinfo_format в тип QGIS.

        Args:
            mapinfo_format: Строка формата из Base_forest_vydely.json

        Returns:
            (QMetaType.Type, length)

        Examples:
            "(Целое)" -> (QMetaType.Type.Int, 0)
            "(Символьное, ограничение по символам 254)" -> (QMetaType.Type.QString, 254)
            "(Символьное, ограничение по символам 50)" -> (QMetaType.Type.QString, 50)
        """
        if not mapinfo_format:
            return QMetaType.Type.QString, 254

        if "Целое" in mapinfo_format:
            return QMetaType.Type.Int, 0

        # Парсим длину из "(Символьное, ограничение по символам N)"
        match = re.search(r"символам\s+(\d+)", mapinfo_format)
        if match:
            length = int(match.group(1))
            return QMetaType.Type.QString, length

        # Default: String 254
        return QMetaType.Type.QString, 254
