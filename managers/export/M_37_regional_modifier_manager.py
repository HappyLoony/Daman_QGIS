# -*- coding: utf-8 -*-
"""
M_37 - Менеджер региональных модификаторов

Читает код региона из метаданных проекта и применяет
цепочку модификаторов к параметрам экспорта.

Паттерн: Singleton через registry.get('M_37')
Домен: export

Модификаторы определены в Msm_37_1_export_modifiers.py
(REGION_EXPORT_MODIFIERS — словарь регион -> список модификаторов)
"""

from typing import Dict, List, Any, Optional

from Daman_QGIS.utils import log_info, log_warning, log_debug


class RegionalModifierManager:
    """
    Менеджер региональных модификаторов.

    Определяет код региона проекта и применяет соответствующие
    модификаторы к экспортным задачам. Модификаторы зарегистрированы
    в REGION_EXPORT_MODIFIERS (Msm_37_1).

    Использование:
        regional_mgr = registry.get('M_37')
        items = regional_mgr.apply_export_modifiers(items, metadata)
    """

    def __init__(self, iface):
        self.iface = iface

    def get_region_code(self, metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """
        Получить код региона из метаданных проекта.

        Args:
            metadata: Метаданные проекта (если уже загружены).
                      Если None, загружает из GeoPackage.

        Returns:
            Код региона ('78', '77', ...) или None
        """
        if metadata is None:
            metadata = self._load_metadata()

        return metadata.get('1_4_1_code_region')

    def is_region(self, code: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Проверить, совпадает ли текущий регион проекта.

        Args:
            code: Код региона для проверки ('78')
            metadata: Метаданные проекта (опционально)

        Returns:
            True если текущий регион совпадает
        """
        current = self.get_region_code(metadata)
        return current == code

    def has_export_modifiers(self, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Проверить, есть ли модификаторы для текущего региона.

        Args:
            metadata: Метаданные проекта (опционально)

        Returns:
            True если для региона зарегистрированы модификаторы
        """
        from .submodules.Msm_37_1_export_modifiers import REGION_EXPORT_MODIFIERS
        region = self.get_region_code(metadata)
        if not region:
            return False
        return region in REGION_EXPORT_MODIFIERS

    def get_export_modifiers(
        self,
        metadata: Optional[Dict[str, Any]] = None
    ) -> list:
        """
        Получить список модификаторов экспорта для текущего региона.

        Args:
            metadata: Метаданные проекта (опционально)

        Returns:
            Список ExportModifier или пустой список
        """
        from .submodules.Msm_37_1_export_modifiers import REGION_EXPORT_MODIFIERS

        region = self.get_region_code(metadata)
        if not region:
            return []

        modifiers = REGION_EXPORT_MODIFIERS.get(region, [])
        if modifiers:
            log_debug(
                f"M_37: Регион {region}: {len(modifiers)} модификаторов экспорта"
            )

        return modifiers

    def apply_export_modifiers(
        self,
        items: List[Dict[str, Any]],
        metadata: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Применить все модификаторы экспорта к списку задач.

        Модификаторы применяются последовательно (chain).
        Каждый модификатор может расширить, изменить или отфильтровать items.

        Args:
            items: Список экспортных задач [{layer, template, extra_context?}, ...]
            metadata: Метаданные проекта

        Returns:
            Трансформированный список задач
        """
        modifiers = self.get_export_modifiers(metadata)
        if not modifiers:
            return items

        region = self.get_region_code(metadata)
        original_count = len(items)

        for modifier in modifiers:
            items = modifier.modify_export_items(items, metadata)

        if len(items) != original_count:
            log_info(
                f"M_37: Регион {region}: {original_count} -> {len(items)} "
                f"экспортных задач после модификаторов"
            )

        return items

    def _load_metadata(self) -> Dict[str, Any]:
        """
        Загрузить метаданные проекта из GeoPackage.

        Returns:
            Словарь метаданных или пустой словарь
        """
        try:
            from Daman_QGIS.tools.F_5_release.submodules.Fsm_5_3_5_export_utils import (
                ExportUtils
            )
            return ExportUtils.get_project_metadata()
        except Exception as e:
            log_warning(f"M_37: Не удалось загрузить метаданные: {e}")
            return {}
