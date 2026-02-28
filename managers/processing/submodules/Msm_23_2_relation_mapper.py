# -*- coding: utf-8 -*-
"""
Msm_23_2 - RelationMapper: Маппинг связей ОКС-ЗУ и обновление слоёв

Назначение:
    1. Обновление полей ОКС_на_ЗУ_* в слоях выборки
    2. Создание обратного маппинга ЗУ -> ОКС
    3. Формирование значений с адресами ("КН - Адрес")

Логика обновления:
    - Слой ОКС (L_2_1_2): заполняет ОКС_на_ЗУ_выписка и ОКС_на_ЗУ_факт
    - Слой ЗУ (Le_2_1_1_1): заполняет те же поля, но с обратным маппингом

Разделитель для множественных значений: "; "
"""

from typing import Dict, List, Optional
from qgis.core import QgsVectorLayer

from Daman_QGIS.utils import log_info, log_warning, log_error


class RelationMapper:
    """Маппинг связей ОКС-ЗУ и обновление слоёв выборки"""

    # Имена полей
    FIELD_VYPISKA = 'ОКС_на_ЗУ_выписка'
    FIELD_FACT = 'ОКС_на_ЗУ_факт'

    # Разделитель для множественных значений
    SEPARATOR = '; '

    def update_selection_layers(
        self,
        oks_layer: QgsVectorLayer,
        zu_layer: QgsVectorLayer,
        vypiska_data: Optional[Dict[str, List[str]]],
        geometry_data: Optional[Dict[str, List[str]]]
    ) -> Dict[str, int]:
        """
        Обновить поля в слоях выборки

        Args:
            oks_layer: Слой ОКС (L_2_1_2_Выборка_ОКС)
            zu_layer: Слой ЗУ (Le_2_1_1_1_Выборка_ЗУ)
            vypiska_data: {КН_ОКС: [список_КН_ЗУ_из_выписки]} или None
            geometry_data: {КН_ОКС: [список_КН_ЗУ_по_геометрии]} или None

        Returns:
            dict: Статистика {'oks_updated': N, 'zu_updated': N}
        """
        stats = {
            'oks_updated': 0,
            'zu_updated': 0
        }

        # Если нет данных - ничего не делаем
        if vypiska_data is None and geometry_data is None:
            log_info("Msm_23_2: Нет данных для обновления")
            return stats

        # 1. Обновляем слой ОКС
        oks_updated = self._update_oks_layer(oks_layer, vypiska_data, geometry_data)
        stats['oks_updated'] = oks_updated

        # 2. Собираем адреса ОКС для формирования "КН - Адрес"
        oks_addresses = self._collect_oks_addresses(oks_layer)

        # 3. Создаём обратный маппинг ЗУ -> ОКС (с адресами)
        zu_vypiska_map = None
        zu_geometry_map = None

        if vypiska_data is not None:
            zu_vypiska_map = self.create_reverse_mapping(vypiska_data, oks_addresses)

        if geometry_data is not None:
            zu_geometry_map = self.create_reverse_mapping(geometry_data, oks_addresses)

        # 4. Обновляем слой ЗУ
        zu_updated = self._update_zu_layer(zu_layer, zu_vypiska_map, zu_geometry_map)
        stats['zu_updated'] = zu_updated

        return stats

    def create_reverse_mapping(
        self,
        oks_to_zu_map: Dict[str, List[str]],
        oks_addresses: Optional[Dict[str, str]] = None
    ) -> Dict[str, List[str]]:
        """
        Создать обратный маппинг ЗУ -> ОКС

        Формат значения: "КН - Адрес" или просто "КН" если адреса нет

        Args:
            oks_to_zu_map: {КН_ОКС: [список_КН_ЗУ]}
            oks_addresses: {КН_ОКС: Адрес} (опционально)

        Returns:
            dict: {КН_ЗУ: [список "КН - Адрес"]}
        """
        zu_to_oks_map: Dict[str, List[str]] = {}

        for oks_kn, zu_list in oks_to_zu_map.items():
            # Формируем значение "КН - Адрес"
            if oks_addresses:
                address = oks_addresses.get(oks_kn)
                if address:
                    oks_value = f"{oks_kn} - {address}"
                else:
                    oks_value = oks_kn
            else:
                oks_value = oks_kn

            for zu_kn in zu_list:
                if zu_kn not in zu_to_oks_map:
                    zu_to_oks_map[zu_kn] = []
                if oks_value not in zu_to_oks_map[zu_kn]:
                    zu_to_oks_map[zu_kn].append(oks_value)

        return zu_to_oks_map

    def _collect_oks_addresses(self, oks_layer: QgsVectorLayer) -> Dict[str, str]:
        """
        Собрать адреса ОКС из слоя

        Args:
            oks_layer: Слой ОКС

        Returns:
            dict: {КН_ОКС: Адрес}
        """
        result: Dict[str, str] = {}

        kn_idx = oks_layer.fields().indexOf('КН')
        address_idx = oks_layer.fields().indexOf('Адрес_Местоположения')

        if kn_idx == -1:
            return result

        if address_idx == -1:
            log_warning("Msm_23_2: Поле 'Адрес_Местоположения' не найдено в слое ОКС")
            return result

        for feature in oks_layer.getFeatures():
            kn = feature[kn_idx]
            if not kn:
                continue

            kn = str(kn).strip()
            address = feature[address_idx]

            if address and str(address).strip() not in ('', '-', 'NULL', 'None'):
                result[kn] = str(address).strip()

        return result

    def _update_oks_layer(
        self,
        oks_layer: QgsVectorLayer,
        vypiska_data: Optional[Dict[str, List[str]]],
        geometry_data: Optional[Dict[str, List[str]]]
    ) -> int:
        """
        Обновить поля в слое ОКС

        Args:
            oks_layer: Слой ОКС
            vypiska_data: {КН_ОКС: [список_КН_ЗУ_из_выписки]} или None
            geometry_data: {КН_ОКС: [список_КН_ЗУ_по_геометрии]} или None

        Returns:
            int: Количество обновлённых объектов
        """
        # Проверяем наличие полей
        vypiska_idx = oks_layer.fields().indexOf(self.FIELD_VYPISKA)
        fact_idx = oks_layer.fields().indexOf(self.FIELD_FACT)

        if vypiska_idx == -1:
            log_warning(f"Msm_23_2: Поле '{self.FIELD_VYPISKA}' не найдено в слое ОКС")
        if fact_idx == -1:
            log_warning(f"Msm_23_2: Поле '{self.FIELD_FACT}' не найдено в слое ОКС")

        if vypiska_idx == -1 and fact_idx == -1:
            log_error("Msm_23_2: Ни одно поле для анализа не найдено в слое ОКС")
            return 0

        kn_idx = oks_layer.fields().indexOf('КН')
        if kn_idx == -1:
            log_error("Msm_23_2: Поле 'КН' не найдено в слое ОКС")
            return 0

        updated_count = 0

        # Начинаем редактирование
        if not oks_layer.startEditing():
            log_error("Msm_23_2: Не удалось начать редактирование слоя ОКС")
            return 0

        for feature in oks_layer.getFeatures():
            kn = feature[kn_idx]
            if not kn:
                continue

            kn = str(kn).strip()
            feature_updated = False

            # Обновляем поле выписки (только если данные переданы)
            if vypiska_data is not None and vypiska_idx != -1:
                zu_list = vypiska_data.get(kn, [])
                value = self.SEPARATOR.join(zu_list) if zu_list else '-'
                if oks_layer.changeAttributeValue(feature.id(), vypiska_idx, value):
                    feature_updated = True

            # Обновляем поле факта (только если данные переданы)
            if geometry_data is not None and fact_idx != -1:
                zu_list = geometry_data.get(kn, [])
                value = self.SEPARATOR.join(zu_list) if zu_list else '-'
                if oks_layer.changeAttributeValue(feature.id(), fact_idx, value):
                    feature_updated = True

            if feature_updated:
                updated_count += 1

        # Сохраняем изменения
        if not oks_layer.commitChanges():
            log_error(f"Msm_23_2: Ошибка сохранения слоя ОКС: {oks_layer.commitErrors()}")
            oks_layer.rollBack()
            return 0

        log_info(f"Msm_23_2: Обновлено {updated_count} ОКС")
        return updated_count

    def _update_zu_layer(
        self,
        zu_layer: QgsVectorLayer,
        zu_vypiska_map: Optional[Dict[str, List[str]]],
        zu_geometry_map: Optional[Dict[str, List[str]]]
    ) -> int:
        """
        Обновить поля в слое ЗУ

        Args:
            zu_layer: Слой ЗУ
            zu_vypiska_map: {КН_ЗУ: [список_КН_ОКС_из_выписок]} или None
            zu_geometry_map: {КН_ЗУ: [список_КН_ОКС_по_геометрии]} или None

        Returns:
            int: Количество обновлённых объектов
        """
        # Если нет данных - ничего не делаем
        if zu_vypiska_map is None and zu_geometry_map is None:
            return 0

        # Проверяем наличие полей
        vypiska_idx = zu_layer.fields().indexOf(self.FIELD_VYPISKA)
        fact_idx = zu_layer.fields().indexOf(self.FIELD_FACT)

        if vypiska_idx == -1:
            log_warning(f"Msm_23_2: Поле '{self.FIELD_VYPISKA}' не найдено в слое ЗУ")
        if fact_idx == -1:
            log_warning(f"Msm_23_2: Поле '{self.FIELD_FACT}' не найдено в слое ЗУ")

        if vypiska_idx == -1 and fact_idx == -1:
            log_warning("Msm_23_2: Поля для анализа ОКС не найдены в слое ЗУ")
            return 0

        kn_idx = zu_layer.fields().indexOf('КН')
        if kn_idx == -1:
            log_error("Msm_23_2: Поле 'КН' не найдено в слое ЗУ")
            return 0

        updated_count = 0

        # Начинаем редактирование
        if not zu_layer.startEditing():
            log_error("Msm_23_2: Не удалось начать редактирование слоя ЗУ")
            return 0

        for feature in zu_layer.getFeatures():
            kn = feature[kn_idx]
            if not kn:
                continue

            kn = str(kn).strip()
            feature_updated = False

            # Обновляем поле выписки (только если данные переданы)
            if zu_vypiska_map is not None and vypiska_idx != -1:
                oks_list = zu_vypiska_map.get(kn, [])
                value = self.SEPARATOR.join(oks_list) if oks_list else '-'
                if zu_layer.changeAttributeValue(feature.id(), vypiska_idx, value):
                    feature_updated = True

            # Обновляем поле факта (только если данные переданы)
            if zu_geometry_map is not None and fact_idx != -1:
                oks_list = zu_geometry_map.get(kn, [])
                value = self.SEPARATOR.join(oks_list) if oks_list else '-'
                if zu_layer.changeAttributeValue(feature.id(), fact_idx, value):
                    feature_updated = True

            if feature_updated:
                updated_count += 1

        # Сохраняем изменения
        if not zu_layer.commitChanges():
            log_error(f"Msm_23_2: Ошибка сохранения слоя ЗУ: {zu_layer.commitErrors()}")
            zu_layer.rollBack()
            return 0

        log_info(f"Msm_23_2: Обновлено {updated_count} ЗУ")
        return updated_count
