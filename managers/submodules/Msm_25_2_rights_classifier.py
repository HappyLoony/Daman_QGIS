# -*- coding: utf-8 -*-
"""
Msm_25_2 - Классификатор прав на земельные участки

Определяет в какой слой L_2_3_* должен попасть объект
на основе полей "Права", "Собственники", "Обременения".

Объект может попасть в несколько слоёв:
- Один основной (по праву собственности)
- Дополнительные (по обременениям)

Перенесено из Fsm_2_3_2_1_rights_classifier.py
"""

from typing import Dict, List, Tuple, Optional

from Daman_QGIS.utils import log_info, log_warning
from Daman_QGIS.managers import get_reference_managers


class Msm_25_2_RightsClassifier:
    """Классификатор прав на земельные участки"""

    # Разделитель для множественных значений в полях
    FIELD_SEPARATOR = " / "

    # Маппинг основных прав собственности (Права + Собственники -> слой)
    # Формат: (право, собственник): full_name_слоя
    PRIMARY_RIGHTS_MAPPING: Dict[Tuple[str, str], str] = {
        # === Собственность + Форма собственности ===
        ("Собственность", "Государственная федеральная"): "L_2_3_1_Права_ЗУ_РФ",
        ("Собственность", "Государственная субъекта РФ"): "L_2_3_2_Права_ЗУ_Суб",
        ("Собственность", "Муниципальная"): "L_2_3_3_Права_ЗУ_Муницип",
        ("Собственность", "Частная"): "L_2_3_4_Права_ЗУ_Частное",
        # === Собственность + Имя собственника (вместо формы) ===
        ("Собственность", "Российская Федерация"): "L_2_3_1_Права_ЗУ_РФ",
        # === Общая собственность ===
        ("Общая долевая собственность", "Частная"): "L_2_3_5_Права_ЗУ_Долевая",
        ("Общая совместная собственность", "Частная"): "L_2_3_5_Права_ЗУ_Долевая",
        # === "Сведения отсутствуют" + Форма собственности ===
        ("Сведения отсутствуют", "Государственная федеральная"): "L_2_3_1_Права_ЗУ_РФ",
        ("Сведения отсутствуют", "Государственная субъекта РФ"): "L_2_3_2_Права_ЗУ_Суб",
        ("Сведения отсутствуют", "Муниципальная"): "L_2_3_3_Права_ЗУ_Муницип",
        ("Сведения отсутствуют", "Частная"): "L_2_3_4_Права_ЗУ_Частное",
        # === "Сведения отсутствуют" + Имя собственника ===
        ("Сведения отсутствуют", "Российская Федерация"): "L_2_3_1_Права_ЗУ_РФ",
    }

    # Маппинг дополнительных прав и обременений (для дублирования объектов)
    # Объект копируется в дополнительные слои если найдено совпадение в полях "Права" или "Обременения"
    # Формат: строка_поиска: full_name_слоя
    ADDITIONAL_RIGHTS_MAPPING: Dict[str, str] = {
        # Права (из поля "Права")
        "Постоянное (бессрочное) пользование": "L_2_3_7_Права_ЗУ_ПБП",
        "Сервитут (Право)": "L_2_3_13_Права_ЗУ_Сервитут",
        # Обременения (из поля "Обременения")
        "Аренда": "L_2_3_9_Права_ЗУ_Аренда",
        "Безвозмездное срочное пользование": "L_2_3_8_Права_ЗУ_БСП",
        "Безвозмездное пользование": "L_2_3_16_Права_ЗУ_БП",
        "Ипотека": "L_2_3_10_Права_ЗУ_Ипотека",
        "Арест": "L_2_3_11_Права_ЗУ_Арест",
        "Доверительное управление": "L_2_3_12_Права_ЗУ_Довер_упр",
        "Сервитут": "L_2_3_13_Права_ЗУ_Сервитут",
        "Рента": "L_2_3_14_Права_ЗУ_Рента",
        "Запрещение сделок": "L_2_3_15_Права_ЗУ_Запрет",
    }

    # Слой для неопознанных участков
    UNKNOWN_LAYER = "L_2_3_6_Права_ЗУ_Свед_нет"

    def __init__(self):
        """Инициализация классификатора"""
        self._rights_layers_config: Optional[List[Dict]] = None

    def get_rights_layers_config(self) -> List[Dict]:
        """
        Получить конфигурацию слоёв прав из Base_layers.json

        Returns:
            List[Dict]: Список данных о слоях прав
        """
        if self._rights_layers_config is not None:
            return self._rights_layers_config

        ref_managers = get_reference_managers()
        layer_ref_manager = ref_managers.layer

        if not layer_ref_manager:
            log_warning("Msm_25_2: Не удалось получить layer reference manager")
            return []

        rights_layers = []
        all_layers = layer_ref_manager.get_base_layers()

        for layer_data in all_layers:
            group = layer_data.get('group', '')
            if group == 'Права':
                rights_layers.append(layer_data)

        self._rights_layers_config = rights_layers
        log_info(f"Msm_25_2: Загружена конфигурация для {len(rights_layers)} слоёв прав")

        return rights_layers

    @staticmethod
    def parse_field(value: Optional[str]) -> List[str]:
        """
        Парсинг поля с множественными значениями

        Разделяет строку по разделителю " / " и очищает пробелы

        Args:
            value: Значение поля (может быть None или пустым)

        Returns:
            List[str]: Список значений (пустой если value=None)

        Examples:
            >>> parse_field("Собственность / Постоянное (бессрочное) пользование")
            ["Собственность", "Постоянное (бессрочное) пользование"]

            >>> parse_field("Собственность")
            ["Собственность"]

            >>> parse_field(None)
            []

            >>> parse_field("-")
            []
        """
        if not value:
            return []

        # Очищаем строку
        value = value.strip()

        # Проверяем на пустую строку или "-"
        if not value or value == "-":
            return []

        # Разделяем по " / " и очищаем
        parts = [part.strip() for part in value.split(Msm_25_2_RightsClassifier.FIELD_SEPARATOR)]

        # Фильтруем пустые значения и "-"
        return [part for part in parts if part and part != "-"]

    @staticmethod
    def classify_primary_layer(
        rights_list: List[str],
        owners_list: List[str]
    ) -> Optional[str]:
        """
        Определение основного слоя по правам и собственникам

        Ищет точное совпадение пары (право, собственник) в PRIMARY_RIGHTS_MAPPING

        Args:
            rights_list: Список прав из поля "Права"
            owners_list: Список собственников из поля "Собственники"

        Returns:
            Optional[str]: full_name слоя или None если не найдено
        """
        # Проверяем все комбинации прав и собственников
        for right in rights_list:
            for owner in owners_list:
                # Ищем точное совпадение
                layer_name = Msm_25_2_RightsClassifier.PRIMARY_RIGHTS_MAPPING.get((right, owner))

                if layer_name:
                    log_info(f"Msm_25_2: Найдено совпадение: '{right}' + '{owner}' -> {layer_name}")
                    return layer_name

        # Совпадение не найдено
        log_warning(f"Msm_25_2: Не найдено совпадение для прав={rights_list}, собственников={owners_list}")
        return None

    @staticmethod
    def classify_additional_layers(
        rights_list: List[str],
        encumbrances_list: List[str]
    ) -> List[str]:
        """
        Определение дополнительных слоёв для дублирования объекта

        Ищет совпадения в "Права" и "Обременения" с ADDITIONAL_RIGHTS_MAPPING

        Args:
            rights_list: Список прав из поля "Права"
            encumbrances_list: Список обременений из поля "Обременения"

        Returns:
            List[str]: Список full_name слоёв для дублирования
        """
        additional_layers = []

        # Объединяем права и обременения для проверки
        all_values = rights_list + encumbrances_list

        # Ищем совпадения
        for value in all_values:
            layer_name = Msm_25_2_RightsClassifier.ADDITIONAL_RIGHTS_MAPPING.get(value)

            if layer_name and layer_name not in additional_layers:
                log_info(f"Msm_25_2: Найдено дополнительное право: '{value}' -> {layer_name}")
                additional_layers.append(layer_name)

        return additional_layers

    def classify_feature(
        self,
        rights_value: Optional[str],
        owners_value: Optional[str],
        encumbrances_value: Optional[str]
    ) -> Tuple[Optional[str], List[str]]:
        """
        Полная классификация объекта по правам, собственникам и обременениям

        Args:
            rights_value: Значение поля "Права"
            owners_value: Значение поля "Собственники"
            encumbrances_value: Значение поля "Обременения"

        Returns:
            Tuple[Optional[str], List[str]]:
                - primary_layer: full_name основного слоя (None если не найдено)
                - additional_layers: список full_name дополнительных слоёв

        Examples:
            >>> classify_feature(
                "Собственность / Постоянное (бессрочное) пользование",
                "Государственная федеральная / Частная",
                None
            )
            ("L_2_3_1_Права_ЗУ_РФ", ["L_2_3_7_Права_ЗУ_ПБП"])

            >>> classify_feature("Собственность", "Частная", "Сервитут (Право)")
            ("L_2_3_4_Права_ЗУ_Частное", ["L_2_3_13_Права_ЗУ_Сервитут"])

            >>> classify_feature("-", "-", "-")
            ("L_2_3_6_Права_ЗУ_Свед_нет", [])
        """
        # Проверяем на отсутствие данных ДО парсинга
        def is_no_data(value: Optional[str]) -> bool:
            """Проверка что поле содержит '-' (нет данных)"""
            if not value:
                return True
            return value.strip() == "-"

        # Если хотя бы одно из ключевых полей = "-" -> в "Свед_нет"
        if is_no_data(rights_value) or is_no_data(owners_value):
            log_info(f"Msm_25_2: Отсутствуют данные о правах или собственниках -> {self.UNKNOWN_LAYER}")
            return (self.UNKNOWN_LAYER, [])

        # Парсим поля
        rights_list = self.parse_field(rights_value)
        owners_list = self.parse_field(owners_value)
        encumbrances_list = self.parse_field(encumbrances_value)

        log_info(f"Msm_25_2: Классификация объекта:")
        log_info(f"  Права: {rights_list}")
        log_info(f"  Собственники: {owners_list}")
        log_info(f"  Обременения: {encumbrances_list}")

        # Определяем основной слой
        primary_layer = self.classify_primary_layer(rights_list, owners_list)

        # Определяем дополнительные слои
        additional_layers = self.classify_additional_layers(rights_list, encumbrances_list)

        log_info(f"Msm_25_2: Результат классификации:")
        log_info(f"  Основной слой: {primary_layer if primary_layer else 'НЕ НАЙДЕН'}")
        log_info(f"  Дополнительные слои: {additional_layers if additional_layers else 'НЕТ'}")

        return primary_layer, additional_layers

    def get_field_names(self) -> Tuple[str, str, str]:
        """
        Получить имена полей для классификации

        Returns:
            Tuple[str, str, str]: (rights_field, owners_field, encumbrances_field)
        """
        return ("Права", "Собственники", "Обременения")
