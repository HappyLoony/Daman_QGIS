# -*- coding: utf-8 -*-
"""
Msm_25_2 - Классификатор прав на земельные участки

Определяет в какой слой L_1_11_* должен попасть объект
на основе полей "Права", "Собственники", "Обременения".

Объект может попасть в несколько слоёв:
- Один основной (по праву собственности)
- Дополнительные (по обременениям)

Перенесено из Fsm_2_3_2_1_rights_classifier.py
"""

from collections import Counter
from typing import Dict, List, Tuple, Optional

from Daman_QGIS.utils import log_info, log_warning

# Lazy import для избежания циклических зависимостей
def _get_reference_managers():
    from Daman_QGIS.managers import get_reference_managers
    return get_reference_managers()


class Msm_25_2_RightsClassifier:
    """Классификатор прав на земельные участки"""

    # Разделитель для множественных значений в полях
    FIELD_SEPARATOR = " / "

    # Маппинг основных прав собственности (Права + Собственники -> слой)
    # Формат: (право, собственник): full_name_слоя
    PRIMARY_RIGHTS_MAPPING: Dict[Tuple[str, str], str] = {
        # === Собственность + Форма собственности ===
        ("Собственность", "Государственная федеральная"): "L_1_11_1_Права_ЗУ_РФ",
        ("Собственность", "Государственная субъекта РФ"): "L_1_11_2_Права_ЗУ_Суб",
        ("Собственность", "Муниципальная"): "L_1_11_3_Права_ЗУ_Муницип",
        ("Собственность", "Частная"): "L_1_11_4_Права_ЗУ_Частное",
        # === Собственность + Имя собственника (вместо формы) ===
        ("Собственность", "Российская Федерация"): "L_1_11_1_Права_ЗУ_РФ",
        # === Собственность + Собственник неизвестен ===
        ("Собственность", "Сведения отсутствуют"): "L_1_11_6_Права_ЗУ_Свед_нет",
        # === Общая собственность (любой собственник -> Долевая) ===
        ("Общая долевая собственность", "Частная"): "L_1_11_5_Права_ЗУ_Долевая",
        ("Общая долевая собственность", "Сведения отсутствуют"): "L_1_11_5_Права_ЗУ_Долевая",
        ("Общая совместная собственность", "Частная"): "L_1_11_5_Права_ЗУ_Долевая",
        ("Общая совместная собственность", "Сведения отсутствуют"): "L_1_11_5_Права_ЗУ_Долевая",
        # === "Сведения отсутствуют" + Форма собственности ===
        ("Сведения отсутствуют", "Государственная федеральная"): "L_1_11_1_Права_ЗУ_РФ",
        ("Сведения отсутствуют", "Государственная субъекта РФ"): "L_1_11_2_Права_ЗУ_Суб",
        ("Сведения отсутствуют", "Муниципальная"): "L_1_11_3_Права_ЗУ_Муницип",
        ("Сведения отсутствуют", "Частная"): "L_1_11_4_Права_ЗУ_Частное",
        # === "Сведения отсутствуют" + Имя собственника ===
        ("Сведения отсутствуют", "Российская Федерация"): "L_1_11_1_Права_ЗУ_РФ",
        # === Нет данных ни о правах, ни о собственниках ===
        ("Сведения отсутствуют", "Сведения отсутствуют"): "L_1_11_6_Права_ЗУ_Свед_нет",
        # === Постоянное (бессрочное) пользование + Форма собственности ===
        ("Постоянное (бессрочное) пользование", "Сведения отсутствуют"): "L_1_11_6_Права_ЗУ_Свед_нет",
        ("Постоянное (бессрочное) пользование", "Государственная федеральная"): "L_1_11_1_Права_ЗУ_РФ",
        ("Постоянное (бессрочное) пользование", "Российская Федерация"): "L_1_11_1_Права_ЗУ_РФ",
        ("Постоянное (бессрочное) пользование", "Государственная субъекта РФ"): "L_1_11_2_Права_ЗУ_Суб",
        ("Постоянное (бессрочное) пользование", "Муниципальная"): "L_1_11_3_Права_ЗУ_Муницип",
        ("Постоянное (бессрочное) пользование", "Частная"): "L_1_11_4_Права_ЗУ_Частное",
        # === Аренда + Форма собственности ===
        ("Аренда", "Государственная федеральная"): "L_1_11_1_Права_ЗУ_РФ",
        ("Аренда", "Российская Федерация"): "L_1_11_1_Права_ЗУ_РФ",
        ("Аренда", "Государственная субъекта РФ"): "L_1_11_2_Права_ЗУ_Суб",
        ("Аренда", "Муниципальная"): "L_1_11_3_Права_ЗУ_Муницип",
        ("Аренда", "Частная"): "L_1_11_4_Права_ЗУ_Частное",
        # === Безвозмездное пользование + Форма собственности ===
        ("Безвозмездное пользование", "Государственная федеральная"): "L_1_11_1_Права_ЗУ_РФ",
        ("Безвозмездное пользование", "Российская Федерация"): "L_1_11_1_Права_ЗУ_РФ",
        ("Безвозмездное пользование", "Государственная субъекта РФ"): "L_1_11_2_Права_ЗУ_Суб",
        ("Безвозмездное пользование", "Муниципальная"): "L_1_11_3_Права_ЗУ_Муницип",
        ("Безвозмездное пользование", "Частная"): "L_1_11_4_Права_ЗУ_Частное",
        # === Безвозмездное срочное пользование + Форма собственности ===
        ("Безвозмездное срочное пользование", "Государственная федеральная"): "L_1_11_1_Права_ЗУ_РФ",
        ("Безвозмездное срочное пользование", "Российская Федерация"): "L_1_11_1_Права_ЗУ_РФ",
        ("Безвозмездное срочное пользование", "Государственная субъекта РФ"): "L_1_11_2_Права_ЗУ_Суб",
        ("Безвозмездное срочное пользование", "Муниципальная"): "L_1_11_3_Права_ЗУ_Муницип",
        ("Безвозмездное срочное пользование", "Частная"): "L_1_11_4_Права_ЗУ_Частное",
    }

    # Маппинг дополнительных прав и обременений (для дублирования объектов)
    # Объект копируется в дополнительные слои если найдено совпадение в полях "Права" или "Обременения"
    # Формат: строка_поиска: full_name_слоя
    ADDITIONAL_RIGHTS_MAPPING: Dict[str, str] = {
        # Права (из поля "Права")
        "Постоянное (бессрочное) пользование": "L_1_11_7_Права_ЗУ_ПБП",
        "Сервитут (Право)": "L_1_11_13_Права_ЗУ_Сервитут",
        # Обременения (из поля "Обременения")
        "Аренда": "L_1_11_9_Права_ЗУ_Аренда",
        "Безвозмездное срочное пользование": "L_1_11_8_Права_ЗУ_БСП",
        "Безвозмездное пользование": "L_1_11_16_Права_ЗУ_БП",
        "Ипотека": "L_1_11_10_Права_ЗУ_Ипотека",
        "Арест": "L_1_11_11_Права_ЗУ_Арест",
        "Доверительное управление": "L_1_11_12_Права_ЗУ_Довер_упр",
        "Сервитут": "L_1_11_13_Права_ЗУ_Сервитут",
        "Рента": "L_1_11_14_Права_ЗУ_Рента",
        "Запрещение сделок": "L_1_11_15_Права_ЗУ_Запрет",
    }

    # Слой для неопознанных участков
    UNKNOWN_LAYER = "L_1_11_6_Права_ЗУ_Свед_нет"

    def __init__(self):
        """Инициализация классификатора"""
        self._rights_layers_config: Optional[List[Dict]] = None
        self._unclassified: Counter = Counter()

    def get_rights_layers_config(self) -> List[Dict]:
        """
        Получить конфигурацию слоёв прав из Base_layers.json

        Returns:
            List[Dict]: Список данных о слоях прав
        """
        if self._rights_layers_config is not None:
            return self._rights_layers_config

        ref_managers = _get_reference_managers()
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
                    return layer_name

        # Совпадение не найдено
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
            ("L_1_11_1_Права_ЗУ_РФ", ["L_1_11_7_Права_ЗУ_ПБП"])

            >>> classify_feature("Собственность", "Частная", "Сервитут (Право)")
            ("L_1_11_4_Права_ЗУ_Частное", ["L_1_11_13_Права_ЗУ_Сервитут"])

            >>> classify_feature("-", "-", "-")
            ("L_1_11_6_Права_ЗУ_Свед_нет", [])
        """
        # Проверяем на отсутствие данных ДО парсинга
        def is_no_data(value: Optional[str]) -> bool:
            """Проверка что поле содержит '-' (нет данных)"""
            if not value:
                return True
            return value.strip() == "-"

        # Если хотя бы одно из ключевых полей = "-" -> в "Свед_нет"
        if is_no_data(rights_value) or is_no_data(owners_value):
            return (self.UNKNOWN_LAYER, [])

        # Парсим поля
        rights_list = self.parse_field(rights_value)
        owners_list = self.parse_field(owners_value)
        encumbrances_list = self.parse_field(encumbrances_value)

        # Определяем основной слой
        primary_layer = self.classify_primary_layer(rights_list, owners_list)

        # Определяем дополнительные слои
        additional_layers = self.classify_additional_layers(rights_list, encumbrances_list)

        # Считаем неклассифицированные для сводки
        if not primary_layer:
            key = (tuple(rights_list), tuple(owners_list))
            self._unclassified[key] += 1

        return primary_layer, additional_layers

    def log_unclassified_summary(self) -> None:
        """Вывести сводку по неклассифицированным объектам и сбросить счётчик"""
        if not self._unclassified:
            return

        total = sum(self._unclassified.values())
        parts = [f"Msm_25_2: Не классифицировано {total} объектов:"]
        for (rights, owners), count in self._unclassified.most_common():
            parts.append(f"  {list(rights)} + {list(owners)}: {count} шт.")
        log_warning("\n".join(parts))
        self._unclassified.clear()

    def get_field_names(self) -> Tuple[str, str, str]:
        """
        Получить имена полей для классификации

        Returns:
            Tuple[str, str, str]: (rights_field, owners_field, encumbrances_field)
        """
        return ("Права", "Собственники", "Обременения")
