# -*- coding: utf-8 -*-
"""
Fsm_2_4_6_SourceProvider - Поиск и валидация исходных слоёв этапности

НАЗНАЧЕНИЕ:
    Находит в проекте слои нарезки (после F_2_3), слой ЗПР и слой кадастровых
    кварталов; проверяет наличие двух полей, которые потребляет F_2_4.

ОСОБЕННОСТИ:
    - Слой попадает в набор только валидным и непустым.
    - Слой, присутствующий в проекте но нечитаемый, копится в `broken_layers`:
      решение об отказе принимает вызывающий.
    - Сверка со схемой Base_cutting здесь НЕ выполняется — это задача M_28.

ИСПОЛЬЗОВАНИЕ:
    Вызывается F_2_4_Staging на старте прогона.
"""

from typing import Dict, List, Optional

from qgis.core import QgsProject, QgsVectorLayer

from Daman_QGIS.constants import LAYER_ZPR_OKS, LAYER_SELECTION_KK
from Daman_QGIS.utils import log_info, log_warning, log_error


class Fsm_2_4_6_SourceProvider:
    """Поиск и валидация исходных слоёв этапности"""

    def __init__(self, layer_mapping: List) -> None:
        """Инициализация

        Args:
            layer_mapping: Маппинг исходных слоёв на слои этапов (из F_2_4_Staging)
        """
        self.LAYER_MAPPING = layer_mapping
        # Слои, которые присутствуют в проекте, но не читаются: вызывающий
        # обязан отказать, а не строить этапность по неполному набору
        self.broken_layers: List[str] = []

    def get_source_layers(self) -> Dict[str, QgsVectorLayer]:
        """Получение исходных слоёв нарезки

        Различает три состояния, у каждого свой сигнал:
        слоя нет в проекте (штатный пропуск), слой есть но не читается
        (ошибка, копится в `broken_layers`), слой пуст (предупреждение).

        `featureCount()` признаком читаемости не является: у здорового
        GPKG-слоя он может вернуть -1 (см. M_48), поэтому отбраковка идёт по
        валидности и составу полей, а счётчик берётся у провайдера.
        """
        result = {}
        project = QgsProject.instance()
        self.broken_layers = []

        for source_poly, _, _, _, _, _, _, _, _ in self.LAYER_MAPPING:
            layers = project.mapLayersByName(source_poly)
            if not layers or not isinstance(layers[0], QgsVectorLayer):
                continue

            layer = layers[0]
            if not layer.isValid() or len(layer.fields()) == 0:
                self.broken_layers.append(source_poly)
                log_error(
                    f"Fsm_2_4_6: слой {source_poly} присутствует, но не читается "
                    f"(isValid={layer.isValid()}, полей={len(layer.fields())})"
                )
                continue

            count = layer.dataProvider().featureCount()
            if count == 0:
                log_warning(
                    f"Fsm_2_4_6: слой {source_poly} пуст, этапность по нему не строится"
                )
                continue

            result[source_poly] = layer
            log_info(f"Fsm_2_4_6: Найден слой {source_poly} ({count} объектов)")

        return result

    def _get_checked_layer(self, layer_name: str) -> Optional[QgsVectorLayer]:
        """Слой проекта, прошедший тот же вахтёр, что и слои нарезки

        Три исхода различаются в журнале: слоя нет, слой сломан, слой пуст.
        `isValid()` истинен и у слоя со сломанным OGR-провайдером — там
        `fields()` пуст, а `featureCount()` равен -1, поэтому одной проверки
        валидности недостаточно.

        Args:
            layer_name: Имя слоя в проекте

        Returns:
            QgsVectorLayer или None, если слой отсутствует, сломан или пуст
        """
        project = QgsProject.instance()
        layers = project.mapLayersByName(layer_name)

        if not layers or not isinstance(layers[0], QgsVectorLayer):
            log_error(f"Fsm_2_4_6: слой {layer_name} отсутствует в проекте")
            return None

        layer = layers[0]
        if not layer.isValid() or len(layer.fields()) == 0:
            log_error(
                f"Fsm_2_4_6: слой {layer_name} присутствует, но не читается "
                f"(isValid={layer.isValid()}, полей={len(layer.fields())})"
            )
            return None

        if layer.dataProvider().featureCount() == 0:
            log_error(f"Fsm_2_4_6: слой {layer_name} пуст")
            return None

        return layer

    def get_zpr_layer(self) -> Optional[QgsVectorLayer]:
        """Получение слоя ЗПР_ОКС"""
        return self._get_checked_layer(LAYER_ZPR_OKS)

    def get_kk_layer(self) -> Optional[QgsVectorLayer]:
        """Получение слоя кадастровых кварталов"""
        return self._get_checked_layer(LAYER_SELECTION_KK)

    def validate_source_layer_fields(
        self,
        source_layers: Dict[str, QgsVectorLayer]
    ) -> List[str]:
        """Проверка двух полей, которые потребляет F_2_4

        Это НЕ сверка со схемой Base_cutting: проверяются ровно те поля,
        без которых этапность не соберёт наследование ОКС. Полная сверка
        структуры — задача валидатора схем (M_28), не этого метода.

        Returns:
            List[str]: Список отсутствующих полей (пустой если всё ОК)
        """
        # Обязательные поля для F_2_4 (наследование ОКС)
        required_fields = {'ОКС_на_ЗУ_выписка', 'ОКС_на_ЗУ_факт'}

        missing = set()
        for layer_name, layer in source_layers.items():
            layer_field_names = {f.name() for f in layer.fields()}
            layer_missing = required_fields - layer_field_names
            if layer_missing:
                log_warning(f"Fsm_2_4_6: Слой {layer_name} не содержит полей: {layer_missing}")
                missing.update(layer_missing)

        return list(missing)
