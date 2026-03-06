# -*- coding: utf-8 -*-
"""
Msm_37_1 - Модификаторы экспорта

Базовый класс ExportModifier и конкретные реализации.
Модификаторы трансформируют список экспортных задач ДО выполнения экспорта.

Паттерн: Modifier Chain — каждый модификатор получает список items
и возвращает (возможно расширенный/изменённый) список items.

Регистрация модификаторов: REGION_EXPORT_MODIFIERS[код_региона] = [модификаторы]
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional

from qgis.core import QgsVectorLayer, QgsFeature, QgsWkbTypes

from Daman_QGIS.utils import log_info, log_warning, log_error


class ExportModifier(ABC):
    """
    Базовый класс модификатора экспорта.

    Каждый модификатор получает список экспортных задач (items) и метаданные проекта,
    и возвращает трансформированный список. Модификатор может:
    - Расширить список (split: 1 item -> N items)
    - Изменить параметры items (filename, context)
    - Отфильтровать items
    - Оставить без изменений
    """

    @abstractmethod
    def modify_export_items(
        self,
        items: List[Dict[str, Any]],
        metadata: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Трансформировать список экспортных задач.

        Args:
            items: Список задач [{layer, template, extra_context?}, ...]
            metadata: Метаданные проекта из _metadata таблицы

        Returns:
            Трансформированный список задач
        """
        pass


class SplitByFeatureModifier(ExportModifier):
    """
    Разделяет экспорт на отдельные файлы по feature.

    Для указанных template_ids каждый feature слоя экспортируется
    в отдельный файл. Именование: ЗУ_1, ЗУ_2, ...

    Создаёт memory layer с одной feature для каждого элемента.
    Memory layer не добавляется в проект QGIS.
    """

    def __init__(self, template_ids: List[str]):
        """
        Args:
            template_ids: ID шаблонов, к которым применяется разделение
        """
        self.template_ids = template_ids

    def modify_export_items(
        self,
        items: List[Dict[str, Any]],
        metadata: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Разделить items с matching template_ids на per-feature items."""
        result: List[Dict[str, Any]] = []

        for item in items:
            template = item['template']

            if template.template_id not in self.template_ids:
                result.append(item)
                continue

            layer = item['layer']
            feature_count = layer.featureCount()

            if feature_count <= 0:
                log_warning(
                    f"Msm_37_1: Слой {layer.name()} пуст, пропуск split"
                )
                result.append(item)
                continue

            log_info(
                f"Msm_37_1: Split по feature для '{layer.name()}' "
                f"({feature_count} features, template={template.template_id})"
            )

            for idx, feature in enumerate(layer.getFeatures(), 1):
                mem_layer = self._create_single_feature_layer(layer, feature)
                if mem_layer is None:
                    log_warning(
                        f"Msm_37_1: Не удалось создать memory layer "
                        f"для feature {idx} слоя {layer.name()}"
                    )
                    continue

                feature_name = f"ЗУ_{idx}"

                result.append({
                    'layer': mem_layer,
                    'template': template,
                    'extra_context': {
                        'feature_name': feature_name,
                        'feature_index': idx,
                        'split_by_feature': True,
                    }
                })

            log_info(
                f"Msm_37_1: Слой '{layer.name()}' разделён "
                f"на {feature_count} экспортных задач"
            )

        return result

    def _create_single_feature_layer(
        self,
        source_layer: QgsVectorLayer,
        feature: QgsFeature
    ) -> Optional[QgsVectorLayer]:
        """
        Создать memory layer с одной feature.

        Args:
            source_layer: Исходный слой (для CRS и полей)
            feature: Feature для копирования

        Returns:
            Memory layer с одной feature или None при ошибке
        """
        try:
            geom_type_str = QgsWkbTypes.displayString(source_layer.wkbType())
            crs_id = source_layer.crs().authid()

            uri = f"{geom_type_str}?crs={crs_id}"
            mem_layer = QgsVectorLayer(uri, "split_feature", "memory")

            if not mem_layer.isValid():
                log_error("Msm_37_1: Не удалось создать memory layer")
                return None

            provider = mem_layer.dataProvider()
            if provider is None:
                return None

            # Копируем структуру полей
            provider.addAttributes(source_layer.fields().toList())
            mem_layer.updateFields()

            # Добавляем feature
            provider.addFeature(feature)

            return mem_layer

        except Exception as e:
            log_error(f"Msm_37_1: Ошибка создания memory layer: {e}")
            return None


# === Конфигурация модификаторов по регионам ===

REGION_EXPORT_MODIFIERS: Dict[str, List[ExportModifier]] = {
    '78': [
        SplitByFeatureModifier(
            template_ids=[
                'coord_cutting_oks_razdel',
                'coord_cutting_oks_ngs',
                'coord_cutting_oks_izm',
            ],
        ),
    ],
}
