# -*- coding: utf-8 -*-
"""
Msm_24_1 - Поиск пар слоёв выписок и выборки для синхронизации

Логика сопоставления:
    Le_1_6_1_* (Выписки ЗУ) -> Le_1_9_1_1_Выборка_ЗУ
    Le_1_6_2_* (Выписки ОКС) -> L_1_9_2_Выборка_ОКС
    Le_1_6_3_* (Выписки ЕЗ) -> Le_1_9_1_1_Выборка_ЗУ (ЕЗ = земельные участки)
    Le_1_6_4_* (Части ЗУ) -> НЕ синхронизируются (только в выписках)

Примечание:
    Выборки - "причесанные" слои из функции 2_1.
    ЕЗ (единое землепользование) - тоже земельные участки, поэтому
    попадают в Le_1_9_1_1_Выборка_ЗУ вместе с обычными ЗУ.

Перенесено из Fsm_2_2_1_layer_matcher.py
"""

from typing import List, Tuple, Optional
from qgis.core import QgsProject, QgsVectorLayer

from Daman_QGIS.constants import (
    LAYER_SELECTION_ZU, LAYER_SELECTION_OKS,
    LAYER_VYPISKA_ZU_PREFIX, LAYER_VYPISKA_OKS_PREFIX, LAYER_VYPISKA_EZ_PREFIX
)
from Daman_QGIS.utils import log_info, log_warning


class Msm_24_1_LayerMatcher:
    """Поиск пар слоёв для синхронизации"""

    # Маппинг префиксов выписок на имена слоёв выборки
    # ЕЗ (единое землепользование) - тоже земельные участки, идут в Выборка_ЗУ
    # ЧЗУ (части ЗУ, Le_1_6_4) НЕ участвуют в синхронизации
    VYPISKA_TO_SELECTION = {
        LAYER_VYPISKA_ZU_PREFIX: LAYER_SELECTION_ZU,      # ЗУ
        LAYER_VYPISKA_OKS_PREFIX: LAYER_SELECTION_OKS,    # ОКС
        LAYER_VYPISKA_EZ_PREFIX: LAYER_SELECTION_ZU,      # ЕЗ -> тоже в Выборка_ЗУ
    }

    def __init__(self):
        """Инициализация"""
        self.project = QgsProject.instance()

    def find_layer_pairs(self) -> List[Tuple[QgsVectorLayer, QgsVectorLayer]]:
        """
        Поиск пар слоёв (выписка, выборка) для синхронизации

        Returns:
            List[(vypiska_layer, selection_layer)]: Список пар слоёв
        """
        pairs = []

        # Получаем все слои проекта
        all_layers = {layer.name(): layer for layer in self.project.mapLayers().values()}

        # Для каждого типа выписок ищем пару
        for vypiska_prefix, selection_name in self.VYPISKA_TO_SELECTION.items():
            # Находим целевой слой выборки
            selection_layer = all_layers.get(selection_name)

            if selection_layer is None:
                log_info(f"Msm_24_1: Слой выборки '{selection_name}' не найден, пропускаем")
                continue

            # Находим все слои выписок с этим префиксом
            vypiska_layers = [
                layer for name, layer in all_layers.items()
                if name.startswith(vypiska_prefix)
            ]

            if not vypiska_layers:
                log_warning(f"Msm_24_1: Слои выписок '{vypiska_prefix}_*' не найдены")
                continue

            # Создаём пары (каждый слой выписки -> слой выборки)
            for vypiska_layer in vypiska_layers:
                # Проверяем что оба слоя валидны
                if vypiska_layer.isValid() and selection_layer.isValid():
                    pairs.append((vypiska_layer, selection_layer))
                    log_info(
                        f"Msm_24_1: Пара найдена: {vypiska_layer.name()} ({vypiska_layer.featureCount()} фич) -> "
                        f"{selection_layer.name()} ({selection_layer.featureCount()} фич)"
                    )
                else:
                    log_warning(
                        f"Msm_24_1: Некорректная пара слоёв: "
                        f"{vypiska_layer.name()} (valid={vypiska_layer.isValid()}) -> "
                        f"{selection_layer.name()} (valid={selection_layer.isValid()})"
                    )

        if not pairs:
            log_warning("Msm_24_1: Не найдено ни одной пары слоёв для синхронизации")
        else:
            log_info(f"Msm_24_1: Найдено {len(pairs)} пар слоёв для синхронизации")

        return pairs

