# -*- coding: utf-8 -*-
"""
Субмодуль F_1_2: Загрузка ООПТ Минприроды (category_id=36507)

Отдельный загрузчик для endpoint 31 (ООПТ Минприроды).
Данные объединяются в Le_1_2_5_21_WFS_ЗОУИТ_ОЗ_ООПТ вместе с другими
источниками (36940 classified + 36948 OOPT).

Содержит логику дедупликации по точному совпадению геометрий (WKB),
применяемую ко всему слою Le_1_2_5_21 после объединения всех источников.
"""

from typing import Optional, Tuple

from qgis.core import QgsVectorLayer

from Daman_QGIS.utils import log_info, log_warning, log_error


# category_id endpoint 31 (ООПТ Минприроды)
OOPT_MINPRIRODY_CATEGORY_ID = 36507


class Fsm_1_2_15_OoptLoader:
    """Загрузчик ООПТ Минприроды (endpoint 31, category_id=36507)"""

    def __init__(self, iface, egrn_loader, api_manager):
        """
        Args:
            iface: Интерфейс QGIS
            egrn_loader: Fsm_1_2_1_EgrnLoader для загрузки данных из NSPD
            api_manager: M_14 APIManager для получения endpoint параметров
        """
        self.iface = iface
        self.egrn_loader = egrn_loader
        self.api_manager = api_manager

    def load_oopt_minprirody(
        self,
        geometry_provider
    ) -> Tuple[Optional[QgsVectorLayer], int]:
        """
        Загрузить ООПТ Минприроды из endpoint 31 (category_id=36507)

        Args:
            geometry_provider: Функция для получения геометрии запроса (буфер 500м)

        Returns:
            tuple: (слой с features, количество объектов) или (None, 0)
        """
        target_layer_name = "Le_1_2_5_21_WFS_ЗОУИТ_ОЗ_ООПТ"

        # Находим endpoint 31 через api_manager
        endpoint = self._find_endpoint(target_layer_name)
        if not endpoint:
            return None, 0

        ep_id = endpoint.get('endpoint_id', '?')
        ep_name = endpoint.get('category_name', 'ООПТ Минприроды')
        log_info(f"Fsm_1_2_15: Загрузка {ep_name} (EP {ep_id}, cat={OOPT_MINPRIRODY_CATEGORY_ID})")

        try:
            layer, count = self.egrn_loader.load_layer_by_endpoint(
                endpoint=endpoint,
                geometry_provider=geometry_provider,
                progress_task=None
            )

            if not layer or count == 0:
                log_info(f"Fsm_1_2_15: {ep_name}: 0 объектов в данной области")
                return None, 0

            log_info(f"Fsm_1_2_15: {ep_name}: загружено {count} объектов")
            return layer, count

        except Exception as e:
            log_error(f"Fsm_1_2_15: Ошибка загрузки {ep_name}: {str(e)}")
            return None, 0

    def deduplicate_by_geometry(self, layer: QgsVectorLayer) -> int:
        """
        Удалить дубликаты по точному совпадению геометрий (WKB match)

        Применяется к итоговому слою Le_1_2_5_21 после объединения
        всех источников (36940 + 36948 + 36507).

        Args:
            layer: Слой для дедупликации (memory layer, editing supported)

        Returns:
            int: Количество удалённых дубликатов
        """
        seen_wkb = set()
        duplicate_ids = []

        for feature in layer.getFeatures():
            if not feature.hasGeometry():
                continue
            wkb = bytes(feature.geometry().asWkb())
            if wkb in seen_wkb:
                duplicate_ids.append(feature.id())
            else:
                seen_wkb.add(wkb)

        if not duplicate_ids:
            log_info("Fsm_1_2_15: Дубликатов геометрий не обнаружено")
            return 0

        layer.startEditing()
        layer.deleteFeatures(duplicate_ids)
        layer.commitChanges()

        log_info(
            f"Fsm_1_2_15: Удалено {len(duplicate_ids)} дубликатов геометрий, "
            f"осталось {layer.featureCount()} объектов"
        )
        return len(duplicate_ids)

    def _find_endpoint(self, target_layer_name: str) -> Optional[dict]:
        """
        Найти endpoint 31 (category_id=36507) среди endpoints для Le_1_2_5_21

        Returns:
            dict с данными endpoint или None
        """
        if not self.api_manager:
            log_error("Fsm_1_2_15: api_manager не инициализирован")
            return None

        endpoints = self.api_manager.get_all_endpoints_by_layer(target_layer_name)
        if not endpoints:
            log_warning(f"Fsm_1_2_15: Нет endpoints для '{target_layer_name}'")
            return None

        # Ищем endpoint с category_id=36507 (ООПТ Минприроды)
        for ep in endpoints:
            if ep.get('category_id') == OOPT_MINPRIRODY_CATEGORY_ID:
                return ep

        log_warning(
            f"Fsm_1_2_15: Endpoint с category_id={OOPT_MINPRIRODY_CATEGORY_ID} "
            f"не найден среди {len(endpoints)} endpoints для '{target_layer_name}'"
        )
        return None
