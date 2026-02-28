# -*- coding: utf-8 -*-
"""
Msm_23_4 - ZuExtractAnalyzer: Анализ выписок ЗУ для заполнения ОКС_на_ЗУ_выписка

Назначение:
    Извлечение данных о связанных ОКС из выписок ЗУ (поле "Включенные_объекты")
    и обновление поля "ОКС_на_ЗУ_выписка" в слое выборки ЗУ.

Логика:
    1. Ищет слои выписок ЗУ (Le_1_6_1_*)
    2. Извлекает поле "Включенные_объекты" для каждого КН ЗУ
    3. Обновляет поле "ОКС_на_ЗУ_выписка" в слое выборки ЗУ
    4. Дедуплицирует значения в пределах одного поля

Зависимости:
    - M_23_oks_zu_analysis_manager (родительский менеджер)
"""

from typing import Dict, List, Optional, Set
from qgis.core import QgsProject, QgsVectorLayer

from Daman_QGIS.utils import log_info, log_warning, log_error


class ZuExtractAnalyzer:
    """Анализатор выписок ЗУ для извлечения связей с ОКС"""

    # Префикс слоёв выписок ЗУ
    VYPISKA_ZU_PREFIX = 'Le_1_6_1_'

    # Поле в выписках ЗУ с КН включённых объектов (ОКС)
    INCLUDED_OBJECTS_FIELD = 'Включенные_объекты'

    # Поле в слое выборки ЗУ для записи результата
    TARGET_FIELD = 'ОКС_на_ЗУ_выписка'

    # Разделитель для множественных значений
    SEPARATOR = '; '

    def extract_oks_from_zu_extracts(
        self,
        zu_kn_list: Optional[List[str]] = None
    ) -> Dict[str, List[str]]:
        """
        Извлечь связи ОКС из выписок ЗУ

        Args:
            zu_kn_list: Список КН ЗУ для фильтрации (если None - все)

        Returns:
            {КН_ЗУ: [список_КН_ОКС]}
        """
        result: Dict[str, List[str]] = {}

        # Ищем слои выписок ЗУ (Le_1_6_1_*)
        vypiska_layers = self._find_zu_extract_layers()

        if not vypiska_layers:
            log_info("Msm_23_4: Слои выписок ЗУ (Le_1_6_1_*) не найдены")
            return result

        log_info(f"Msm_23_4: Найдено {len(vypiska_layers)} слоёв выписок ЗУ")

        # Извлекаем данные из всех слоёв выписок
        for vypiska_layer in vypiska_layers:
            self._process_vypiska_layer(vypiska_layer, result, zu_kn_list)

        # Логируем результат
        non_empty = {k: v for k, v in result.items() if v}
        log_info(
            f"Msm_23_4: Извлечено данных о связанных ОКС для {len(non_empty)} ЗУ "
            f"из {len(result)} обработанных"
        )

        return result

    def update_zu_selection_layer(
        self,
        zu_layer: QgsVectorLayer,
        oks_data: Dict[str, List[str]]
    ) -> int:
        """
        Обновить поле ОКС_на_ЗУ_выписка в слое выборки ЗУ

        Args:
            zu_layer: Слой выборки ЗУ
            oks_data: {КН_ЗУ: [список_КН_ОКС]}

        Returns:
            int: Количество обновлённых объектов
        """
        if not oks_data:
            log_info("Msm_23_4: Нет данных для обновления слоя ЗУ")
            return 0

        # Проверяем наличие полей
        target_idx = zu_layer.fields().indexOf(self.TARGET_FIELD)
        if target_idx == -1:
            log_warning(f"Msm_23_4: Поле '{self.TARGET_FIELD}' не найдено в слое ЗУ")
            return 0

        kn_idx = zu_layer.fields().indexOf('КН')
        if kn_idx == -1:
            log_error("Msm_23_4: Поле 'КН' не найдено в слое ЗУ")
            return 0

        updated_count = 0

        # Начинаем редактирование
        if not zu_layer.startEditing():
            log_error("Msm_23_4: Не удалось начать редактирование слоя ЗУ")
            return 0

        for feature in zu_layer.getFeatures():
            kn = feature[kn_idx]
            if not kn:
                continue

            kn = str(kn).strip()

            # Получаем текущее значение поля
            current_value = feature[target_idx]
            current_oks: Set[str] = set()

            if current_value and str(current_value).strip() not in ('', '-', 'NULL', 'None'):
                # Парсим существующие значения
                for item in str(current_value).split(';'):
                    item = item.strip()
                    if item and item not in ('-', 'NULL', 'None'):
                        current_oks.add(item)

            # Добавляем новые значения из выписок
            new_oks = oks_data.get(kn, [])
            for oks in new_oks:
                if oks:
                    current_oks.add(oks)

            # Формируем итоговое значение
            if current_oks:
                # Сортируем для консистентности
                value = self.SEPARATOR.join(sorted(current_oks))
            else:
                value = '-'

            # Обновляем только если значение изменилось
            old_value = str(current_value) if current_value else '-'
            if value != old_value:
                if zu_layer.changeAttributeValue(feature.id(), target_idx, value):
                    updated_count += 1

        # Сохраняем изменения
        if not zu_layer.commitChanges():
            log_error(f"Msm_23_4: Ошибка сохранения слоя ЗУ: {zu_layer.commitErrors()}")
            zu_layer.rollBack()
            return 0

        log_info(f"Msm_23_4: Обновлено {updated_count} ЗУ (поле '{self.TARGET_FIELD}')")
        return updated_count

    def has_zu_extracts(self) -> bool:
        """
        Проверить наличие слоёв выписок ЗУ с полем Включенные_объекты

        Returns:
            True если есть выписки ЗУ с данными
        """
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not layer.name().startswith(self.VYPISKA_ZU_PREFIX):
                continue

            # Проверяем наличие поля Включенные_объекты
            if layer.fields().indexOf(self.INCLUDED_OBJECTS_FIELD) != -1:
                if layer.featureCount() > 0:
                    return True

        return False

    def _find_zu_extract_layers(self) -> List[QgsVectorLayer]:
        """Найти все слои выписок ЗУ в проекте"""
        return [
            layer for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer)
            and layer.name().startswith(self.VYPISKA_ZU_PREFIX)
        ]

    def _process_vypiska_layer(
        self,
        layer: QgsVectorLayer,
        result: Dict[str, List[str]],
        zu_kn_filter: Optional[List[str]] = None
    ):
        """
        Обработать один слой выписок ЗУ

        Args:
            layer: Слой выписки ЗУ
            result: Словарь для накопления результатов
            zu_kn_filter: Фильтр по КН ЗУ (если None - все)
        """
        # Проверяем наличие нужных полей
        included_idx = layer.fields().indexOf(self.INCLUDED_OBJECTS_FIELD)
        if included_idx == -1:
            log_info(f"Msm_23_4: Поле '{self.INCLUDED_OBJECTS_FIELD}' не найдено в {layer.name()}")
            return

        kn_idx = layer.fields().indexOf('КН')
        if kn_idx == -1:
            log_warning(f"Msm_23_4: Поле 'КН' не найдено в {layer.name()}")
            return

        for feature in layer.getFeatures():
            zu_kn = feature[kn_idx]
            if not zu_kn:
                continue

            zu_kn = str(zu_kn).strip()

            # Фильтрация по списку КН (если задан)
            if zu_kn_filter and zu_kn not in zu_kn_filter:
                continue

            # Инициализируем список если нужно
            if zu_kn not in result:
                result[zu_kn] = []

            # Извлекаем включённые объекты
            included_value = feature[included_idx]
            if not included_value:
                continue

            value_str = str(included_value).strip()
            if value_str in ('', '-', 'NULL', 'None'):
                continue

            # Парсим значения (разделитель: "; " или ", ")
            if ';' in value_str:
                oks_list = [item.strip() for item in value_str.split(';')]
            else:
                oks_list = [item.strip() for item in value_str.split(',')]

            # Добавляем уникальные значения
            for oks_kn in oks_list:
                if oks_kn and oks_kn not in ('-', 'NULL', '') and oks_kn not in result[zu_kn]:
                    result[zu_kn].append(oks_kn)
