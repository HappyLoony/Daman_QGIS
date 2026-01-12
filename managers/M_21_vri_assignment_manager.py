# -*- coding: utf-8 -*-
"""
M_21_VRIAssignmentManager - Менеджер присвоения ВРИ

Функции:
1. Валидация ВРИ из слоя ЗПР по базе данных VRI.json (по полю full_name)
2. Присвоение План_ВРИ в слоях нарезки на основе ВРИ из ЗПР
3. Определение поля Общая_земля (Отнесен/Не отнесен к территориям общего пользования)

Поддерживает множественные ВРИ через разделитель "," в одном поле.
Пример: "Среднеэтажная жилая застройка (код 2.5), Многоэтажная жилая застройка (код 2.6)"

Используется в:
- F_3_1 (нарезка) - итоговые слои
- F_3_3 (ЗПР ОКС) - итоговые слои
- F_3_4 (этапность) - только слой "Итог"
"""

import json
import os
from typing import Dict, List, Optional, Set, Tuple, Any

from qgis.core import QgsVectorLayer, QgsFeature

from Daman_QGIS.utils import log_info, log_warning, log_error


class VRIAssignmentManager:
    """Менеджер присвоения и валидации ВРИ"""

    # Возможные имена поля ВРИ в слое ЗПР
    VRI_FIELD_NAMES = ['VRI', 'ВРИ', 'vri']

    # Значения для поля Общая_земля
    PUBLIC_TERRITORY_YES = "Отнесен"
    PUBLIC_TERRITORY_NO = "Не отнесен"

    def __init__(self, plugin_dir: Optional[str] = None) -> None:
        """Инициализация менеджера

        Args:
            plugin_dir: Путь к папке плагина (если None - определяется автоматически)
        """
        if plugin_dir:
            self._plugin_dir = plugin_dir
        else:
            self._plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        self._vri_data: List[Dict] = []
        self._vri_by_full_name: Dict[str, Dict] = {}
        self._vri_by_code: Dict[str, Dict] = {}
        self._loaded = False

    def _load_vri_database(self) -> bool:
        """Загрузка базы данных ВРИ

        Returns:
            True если загрузка успешна
        """
        if self._loaded:
            return True

        from Daman_QGIS.constants import DATA_REFERENCE_PATH
        json_path = os.path.join(DATA_REFERENCE_PATH, 'VRI.json')

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                self._vri_data = json.load(f)

            # Строим индексы для быстрого поиска
            for vri in self._vri_data:
                full_name = vri.get('full_name', '')
                code = vri.get('code', '')

                if full_name:
                    # Нормализуем для поиска (lowercase, без лишних пробелов)
                    normalized = full_name.strip().lower()
                    self._vri_by_full_name[normalized] = vri

                if code:
                    self._vri_by_code[code.strip()] = vri

            self._loaded = True
            log_info(f"M_21: Загружена база ВРИ ({len(self._vri_data)} записей)")
            return True

        except Exception as e:
            log_error(f"M_21: Ошибка загрузки VRI.json: {e}")
            return False

    def _find_vri_field(self, layer: QgsVectorLayer) -> Optional[str]:
        """Поиск поля ВРИ в слое

        Args:
            layer: Слой для поиска

        Returns:
            Имя поля или None
        """
        field_names = [f.name() for f in layer.fields()]

        for vri_name in self.VRI_FIELD_NAMES:
            if vri_name in field_names:
                return vri_name

        return None

    def _parse_multiple_vri(self, vri_string: str) -> List[str]:
        """Парсинг строки с множественными ВРИ

        ВРИ могут быть перечислены через запятую. Каждый ВРИ имеет формат:
        "Название (код X.Y.Z)"

        Разделитель: запятая с пробелом после закрывающей скобки ", "
        Например: "ВРИ1 (код 2.5), ВРИ2 (код 2.6)"

        Args:
            vri_string: Строка с одним или несколькими ВРИ

        Returns:
            Список отдельных ВРИ (очищенных от лишних пробелов и кавычек)
        """
        if not vri_string:
            return []

        # Убираем внешние кавычки если есть
        vri_string = vri_string.strip().strip('"\'')

        # Убираем переносы строк и лишние пробелы
        vri_string = ' '.join(vri_string.split())

        # Разделитель: запятая после закрывающей скобки ")"
        # Паттерн: "), " - конец одного ВРИ, начало следующего
        # Используем split по "), " и восстанавливаем скобку
        parts = vri_string.split('), ')

        result = []
        for i, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue

            # Добавляем обратно закрывающую скобку для всех кроме последнего
            if i < len(parts) - 1:
                part = part + ')'

            result.append(part)

        return result

    def _validate_single_vri(self, vri_str: str) -> bool:
        """Проверка одного значения ВРИ на валидность

        Args:
            vri_str: Строка с одним ВРИ

        Returns:
            True если ВРИ найден в базе данных
        """
        # Удаляем ВСЕ кавычки из строки (они могут быть внутри из-за данных ЕГРН)
        cleaned = vri_str.replace('"', '').replace("'", '').strip()
        normalized = cleaned.lower()

        # Поиск по full_name
        if normalized in self._vri_by_full_name:
            return True

        # Поиск по коду
        if cleaned in self._vri_by_code:
            return True

        return False

    def _get_vri_data_for_single(self, vri_str: str) -> Optional[Dict]:
        """Получить данные ВРИ для одного значения

        Args:
            vri_str: Строка с одним ВРИ

        Returns:
            Словарь с данными ВРИ или None
        """
        # Удаляем ВСЕ кавычки из строки (они могут быть внутри из-за данных ЕГРН)
        # Пример: "Растениеводство" (код 1.1) → Растениеводство (код 1.1)
        cleaned = vri_str.replace('"', '').replace("'", '').strip()
        normalized = cleaned.lower()

        if normalized in self._vri_by_full_name:
            return self._vri_by_full_name[normalized]

        # Поиск по коду (без нормализации регистра)
        if cleaned in self._vri_by_code:
            return self._vri_by_code[cleaned]

        return None

    def validate_zpr_vri(
        self,
        zpr_layer: QgsVectorLayer
    ) -> Tuple[bool, List[str]]:
        """Валидация ВРИ в слое ЗПР

        Проверяет что все значения ВРИ в слое ЗПР соответствуют
        записям в базе данных VRI.json (по полю full_name).

        Поддерживает множественные ВРИ через разделитель ",".
        Каждый ВРИ в списке проверяется отдельно.

        Args:
            zpr_layer: Слой ЗПР (L_2_4_1_ЗПР_ОКС и т.д.)

        Returns:
            Tuple:
                - bool: True если все ВРИ валидны
                - List[str]: Список ошибок
        """
        if not self._load_vri_database():
            return False, ["Не удалось загрузить базу данных ВРИ"]

        # Ищем поле ВРИ
        vri_field = self._find_vri_field(zpr_layer)
        if not vri_field:
            return False, [
                f"В слое {zpr_layer.name()} отсутствует поле VRI/ВРИ. "
                "Добавьте колонку VRI в DXF файл ЗПР и заполните значения ВРИ."
            ]

        errors: List[str] = []
        empty_vri_ids: List[int] = []
        invalid_vri: Dict[str, List[int]] = {}  # {vri_value: [feature_ids]}

        for feature in zpr_layer.getFeatures():
            feature_id = feature['ID'] if 'ID' in feature.fields().names() else feature.id()
            vri_value = feature[vri_field]

            # Проверка на пустое значение
            if not vri_value or str(vri_value).strip() in ('', '-', 'NULL', 'None'):
                empty_vri_ids.append(feature_id)
                continue

            vri_str = str(vri_value).strip()

            # Парсим множественные ВРИ (через запятую)
            vri_list = self._parse_multiple_vri(vri_str)

            if not vri_list:
                empty_vri_ids.append(feature_id)
                continue

            # Валидация каждого ВРИ из списка
            for single_vri in vri_list:
                if not self._validate_single_vri(single_vri):
                    if single_vri not in invalid_vri:
                        invalid_vri[single_vri] = []
                    if feature_id not in invalid_vri[single_vri]:
                        invalid_vri[single_vri].append(feature_id)

        # Формируем ошибки
        if empty_vri_ids:
            errors.append(
                f"Пустое значение ВРИ у контуров ЗПР с ID: {', '.join(map(str, empty_vri_ids))}. "
                "Заполните поле VRI в атрибутах слоя ЗПР."
            )

        for vri_value, ids in invalid_vri.items():
            errors.append(
                f"Невалидный ВРИ '{vri_value}' у контуров с ID: {', '.join(map(str, ids))}. "
                "Проверьте соответствие базе данных VRI.json."
            )

        is_valid = len(errors) == 0

        if is_valid:
            log_info(f"M_21: Валидация ВРИ в слое {zpr_layer.name()} - OK")
        else:
            for error in errors:
                log_warning(f"M_21: {error}")

        return is_valid, errors

    def get_vri_for_zpr_id(
        self,
        zpr_layer: QgsVectorLayer,
        zpr_id: int
    ) -> Optional[List[Dict]]:
        """Получить данные ВРИ для конкретного контура ЗПР

        Поддерживает множественные ВРИ - возвращает список.

        Args:
            zpr_layer: Слой ЗПР
            zpr_id: ID контура ЗПР

        Returns:
            Список словарей с данными ВРИ или None
        """
        if not self._load_vri_database():
            return None

        vri_field = self._find_vri_field(zpr_layer)
        if not vri_field:
            return None

        # Ищем feature по ID
        for feature in zpr_layer.getFeatures():
            feature_id = feature['ID'] if 'ID' in feature.fields().names() else feature.id()

            if feature_id == zpr_id:
                vri_value = feature[vri_field]
                if not vri_value or str(vri_value).strip() in ('', '-', 'NULL', 'None'):
                    return None

                vri_str = str(vri_value).strip()

                # Парсим множественные ВРИ
                vri_list = self._parse_multiple_vri(vri_str)

                if not vri_list:
                    return None

                # Получаем данные для каждого ВРИ
                result = []
                for single_vri in vri_list:
                    vri_data = self._get_vri_data_for_single(single_vri)
                    if vri_data:
                        result.append(vri_data)

                return result if result else None

        return None

    def get_plan_vri(
        self,
        zpr_layer: QgsVectorLayer,
        zpr_id: int
    ) -> str:
        """Получить значение для поля План_ВРИ

        Для множественных ВРИ возвращает строку с разделителем ", ".

        Args:
            zpr_layer: Слой ЗПР
            zpr_id: ID контура ЗПР

        Returns:
            Значения full_name через ", " или "-"
        """
        vri_data_list = self.get_vri_for_zpr_id(zpr_layer, zpr_id)
        if vri_data_list:
            full_names = [vri.get('full_name', '') for vri in vri_data_list if vri.get('full_name')]
            if full_names:
                return ', '.join(full_names)
        return "-"

    def get_public_territory_status(
        self,
        zpr_layer: QgsVectorLayer,
        zpr_id: int
    ) -> str:
        """Получить значение для поля Общее (территория общего пользования)

        Для множественных ВРИ: если хотя бы один ВРИ относится к территории
        общего пользования - возвращает "Отнесен".

        Args:
            zpr_layer: Слой ЗПР
            zpr_id: ID контура ЗПР

        Returns:
            "Отнесен" или "Не отнесен" или "-"
        """
        vri_data_list = self.get_vri_for_zpr_id(zpr_layer, zpr_id)
        if vri_data_list:
            # Если хотя бы один ВРИ - территория общего пользования
            for vri_data in vri_data_list:
                if vri_data.get('is_public_territory', False):
                    return self.PUBLIC_TERRITORY_YES
            return self.PUBLIC_TERRITORY_NO
        return "-"

    def assign_vri_to_features(
        self,
        zpr_layer: QgsVectorLayer,
        features_data: List[Dict[str, Any]],
        zpr_id_key: str = 'zpr_id'
    ) -> List[Dict[str, Any]]:
        """Присвоить План_ВРИ и Общее для списка объектов

        Поддерживает множественные ВРИ через разделитель ",".

        Args:
            zpr_layer: Слой ЗПР
            features_data: Список словарей с данными объектов
                          Каждый словарь должен содержать:
                          - 'attributes': dict с атрибутами
                          - zpr_id_key: ID связанного контура ЗПР
            zpr_id_key: Ключ для получения ID ЗПР из словаря

        Returns:
            Обновлённый список с заполненными План_ВРИ и Общее
        """
        if not self._load_vri_database():
            log_warning("M_21: База ВРИ не загружена, пропуск присвоения")
            return features_data

        vri_field = self._find_vri_field(zpr_layer)
        if not vri_field:
            log_warning(f"M_21: Поле VRI не найдено в слое {zpr_layer.name()}")
            return features_data

        # Строим кэш ВРИ по ID контуров ЗПР
        # Теперь кэш хранит список ВРИ для каждого контура
        zpr_vri_cache: Dict[int, List[Dict]] = {}
        for feature in zpr_layer.getFeatures():
            feature_id = feature['ID'] if 'ID' in feature.fields().names() else feature.id()
            vri_value = feature[vri_field]

            if vri_value and str(vri_value).strip() not in ('', '-', 'NULL', 'None'):
                vri_str = str(vri_value).strip()

                # Парсим множественные ВРИ
                vri_list = self._parse_multiple_vri(vri_str)

                vri_data_list = []
                for single_vri in vri_list:
                    vri_data = self._get_vri_data_for_single(single_vri)
                    if vri_data:
                        vri_data_list.append(vri_data)

                if vri_data_list:
                    zpr_vri_cache[feature_id] = vri_data_list

        # Присваиваем значения
        assigned_count = 0
        for item in features_data:
            zpr_id = item.get(zpr_id_key)
            attrs = item.get('attributes', {})

            if zpr_id is not None and zpr_id in zpr_vri_cache:
                vri_data_list = zpr_vri_cache[zpr_id]

                # План_ВРИ - объединяем все full_name через ", "
                full_names = [vri.get('full_name', '') for vri in vri_data_list if vri.get('full_name')]
                attrs['План_ВРИ'] = ', '.join(full_names) if full_names else '-'

                # Общая_земля - если хотя бы один ВРИ относится к территории общего пользования
                is_public = any(vri.get('is_public_territory', False) for vri in vri_data_list)
                attrs['Общая_земля'] = self.PUBLIC_TERRITORY_YES if is_public else self.PUBLIC_TERRITORY_NO

                assigned_count += 1
            else:
                # Нет привязки к ЗПР или нет ВРИ
                if 'План_ВРИ' not in attrs or attrs['План_ВРИ'] in (None, '', 'NULL'):
                    attrs['План_ВРИ'] = '-'
                if 'Общая_земля' not in attrs or attrs['Общая_земля'] in (None, '', 'NULL'):
                    attrs['Общая_земля'] = '-'

        log_info(f"M_21: Присвоено ВРИ для {assigned_count} из {len(features_data)} объектов")
        return features_data

    def get_all_vri(self) -> List[Dict]:
        """Получить все записи ВРИ из базы данных

        Returns:
            Список всех ВРИ
        """
        if not self._load_vri_database():
            return []
        return self._vri_data.copy()

    def get_vri_by_code(self, code: str) -> Optional[Dict]:
        """Получить ВРИ по коду

        Args:
            code: Код ВРИ (например "2.5")

        Returns:
            Словарь с данными ВРИ или None
        """
        if not self._load_vri_database():
            return None
        return self._vri_by_code.get(code.strip())

    def get_public_territory_vri_codes(self) -> Set[str]:
        """Получить коды ВРИ, относящихся к территориям общего пользования

        Returns:
            Множество кодов ВРИ с is_public_territory=true
        """
        if not self._load_vri_database():
            return set()

        return {
            vri['code']
            for vri in self._vri_data
            if vri.get('is_public_territory', False)
        }

    # =========================================================================
    # DEPRECATED: Модальный ВРИ закомментирован - заменён на геометрическое
    # определение по пересечению с ЗПР (assign_vri_by_zpr_geometry)
    # =========================================================================
    # def assign_modal_vri_for_merging_contours(
    #     self,
    #     features_data: List[Dict[str, Any]]
    # ) -> List[Dict[str, Any]]:
    #     """Присвоение единого модального ВРИ для всех контуров, которые будут объединяться
    #
    #     Для контуров с ID != zpr_id (которые будут объединяться на 2 этапе):
    #     1. Собирает ВСЕ ВРИ из всех объединяемых контуров проекта
    #     2. Валидирует каждый ВРИ по базе VRI.json (невалидные отбрасываются)
    #     3. Определяет ЕДИНЫЙ модальный (наиболее частый) ВРИ для всего проекта
    #     4. Записывает full_name из базы в План_ВРИ для ВСЕХ объединяемых контуров
    #     5. Пересчитывает Общая_земля на основе модального ВРИ
    #
    #     Вызывается ПОСЛЕ assign_vri_to_features() для замены План_ВРИ
    #     у объединяемых контуров.
    #
    #     Args:
    #         features_data: Список словарей с данными контуров 1 этапа
    #
    #     Returns:
    #         Обновлённый список features_data
    #     """
    #     from collections import Counter
    #
    #     if not features_data:
    #         return features_data
    #
    #     # Загружаем базу ВРИ
    #     if not self._load_vri_database():
    #         log_error("M_21: Не удалось загрузить базу VRI.json для модального ВРИ")
    #         return features_data
    #
    #     # Собираем индексы всех контуров, которые будут объединяться (ID != zpr_id)
    #     merging_indices: List[int] = []
    #
    #     for idx, item in enumerate(features_data):
    #         attrs = item.get('attributes', {})
    #         feature_id = attrs.get('ID')
    #         zpr_id = item.get('zpr_id')
    #
    #         # Контур будет объединяться если его ID != zpr_id
    #         if zpr_id is not None and feature_id is not None and feature_id != zpr_id:
    #             merging_indices.append(idx)
    #
    #     if not merging_indices:
    #         return features_data
    #
    #     # Собираем ВСЕ ВРИ из объединяемых контуров и валидируем
    #     valid_vri_data: List[Dict] = []
    #     skipped_invalid = 0
    #
    #     for idx in merging_indices:
    #         attrs = features_data[idx].get('attributes', {})
    #         vri = attrs.get('ВРИ')
    #         if not vri or str(vri).strip() in ('', '-', 'NULL', 'None'):
    #             continue
    #
    #         vri_str = str(vri).strip()
    #         # Валидируем через базу данных
    #         vri_data = self._get_vri_data_for_single(vri_str)
    #         if vri_data:
    #             valid_vri_data.append(vri_data)
    #         else:
    #             skipped_invalid += 1
    #
    #     if not valid_vri_data:
    #         log_warning("M_21: Нет валидных ВРИ среди объединяемых контуров")
    #         return features_data
    #
    #     # Определяем ЕДИНЫЙ модальный ВРИ для всего проекта
    #     full_names = [vri.get('full_name', '') for vri in valid_vri_data]
    #     vri_counter = Counter(full_names)
    #     modal_full_name, modal_count = vri_counter.most_common(1)[0]
    #
    #     # Находим данные для модального ВРИ
    #     modal_vri_data = next(
    #         (vri for vri in valid_vri_data if vri.get('full_name') == modal_full_name),
    #         None
    #     )
    #
    #     if not modal_vri_data:
    #         log_warning(f"M_21: Не удалось найти данные для модального ВРИ")
    #         return features_data
    #
    #     plan_vri = modal_vri_data.get('full_name', '-')
    #     is_public = modal_vri_data.get('is_public_territory', False)
    #
    #     # Присваиваем ЕДИНЫЙ модальный ВРИ всем объединяемым контурам
    #     for idx in merging_indices:
    #         attrs = features_data[idx].get('attributes', {})
    #         attrs['План_ВРИ'] = plan_vri
    #         attrs['Общая_земля'] = self.PUBLIC_TERRITORY_YES if is_public else self.PUBLIC_TERRITORY_NO
    #
    #     log_info(f"M_21: Модальный ВРИ '{plan_vri}' присвоен {len(merging_indices)} контурам")
    #     return features_data
    # =========================================================================

    def assign_vri_by_zpr_geometry(
        self,
        features_data: List[Dict[str, Any]],
        zpr_layer: QgsVectorLayer
    ) -> List[Dict[str, Any]]:
        """Присвоение План_ВРИ для контуров 1 этапа на основе геометрического пересечения с ЗПР

        Для контуров с ID != zpr_id (которые будут объединяться на 2 этапе):
        1. Находит все контуры ЗПР, с которыми пересекается участок
        2. Выбирает ЗПР с максимальной площадью пересечения
        3. Присваивает План_ВРИ и Общая_земля из этого контура ЗПР

        Вызывается ПОСЛЕ assign_vri_to_features() для замены План_ВРИ
        у объединяемых контуров.

        Args:
            features_data: Список словарей с данными контуров 1 этапа
            zpr_layer: Слой ЗПР для геометрического определения

        Returns:
            Обновлённый список features_data
        """
        if not features_data:
            return features_data

        if not zpr_layer or not zpr_layer.isValid():
            log_warning("M_21: Слой ЗПР не передан или невалиден для геометрического ВРИ")
            return features_data

        # Загружаем базу ВРИ
        if not self._load_vri_database():
            log_error("M_21: Не удалось загрузить базу VRI.json для геометрического ВРИ")
            return features_data

        # Ищем поле ВРИ в слое ЗПР
        vri_field = self._find_vri_field(zpr_layer)
        if not vri_field:
            log_warning(f"M_21: Поле VRI не найдено в слое ЗПР {zpr_layer.name()}")
            return features_data

        # Кэшируем данные ЗПР (геометрия, ID, ВРИ)
        zpr_cache: List[Dict] = []
        for zpr_feature in zpr_layer.getFeatures():
            zpr_geom = zpr_feature.geometry()
            if zpr_geom.isEmpty():
                continue

            zpr_id = zpr_feature['ID'] if 'ID' in zpr_feature.fields().names() else zpr_feature.id()
            vri_value = zpr_feature[vri_field]

            if not vri_value or str(vri_value).strip() in ('', '-', 'NULL', 'None'):
                continue

            vri_str = str(vri_value).strip()
            # Парсим множественные ВРИ
            vri_list = self._parse_multiple_vri(vri_str)

            vri_data_list = []
            for single_vri in vri_list:
                vri_data = self._get_vri_data_for_single(single_vri)
                if vri_data:
                    vri_data_list.append(vri_data)

            if vri_data_list:
                zpr_cache.append({
                    'id': int(zpr_id) if zpr_id else zpr_feature.id(),
                    'geometry': zpr_geom,
                    'vri_data_list': vri_data_list
                })

        if not zpr_cache:
            log_warning("M_21: Нет валидных ЗПР с ВРИ для геометрического определения")
            return features_data

        # Собираем индексы контуров, которые будут объединяться (ID != zpr_id)
        merging_indices: List[int] = []

        for idx, item in enumerate(features_data):
            attrs = item.get('attributes', {})
            feature_id = attrs.get('ID')
            zpr_id = item.get('zpr_id')

            # Контур будет объединяться если его ID != zpr_id
            if zpr_id is not None and feature_id is not None and feature_id != zpr_id:
                merging_indices.append(idx)

        if not merging_indices:
            return features_data

        assigned_count = 0

        # Для каждого объединяемого контура находим ЗПР по геометрии
        for idx in merging_indices:
            item = features_data[idx]
            geom = item.get('geometry')

            if not geom or geom.isEmpty():
                continue

            # Находим ЗПР с максимальной площадью пересечения
            best_zpr = None
            best_intersection_area = 0.0

            for zpr in zpr_cache:
                intersection = geom.intersection(zpr['geometry'])
                if intersection.isEmpty():
                    continue

                intersection_area = intersection.area()
                if intersection_area > best_intersection_area:
                    best_intersection_area = intersection_area
                    best_zpr = zpr

            if best_zpr:
                vri_data_list = best_zpr['vri_data_list']
                attrs = item.get('attributes', {})

                # План_ВРИ - объединяем все full_name через ", "
                full_names = [vri.get('full_name', '') for vri in vri_data_list if vri.get('full_name')]
                attrs['План_ВРИ'] = ', '.join(full_names) if full_names else '-'

                # Общая_земля - если хотя бы один ВРИ относится к территории общего пользования
                is_public = any(vri.get('is_public_territory', False) for vri in vri_data_list)
                attrs['Общая_земля'] = self.PUBLIC_TERRITORY_YES if is_public else self.PUBLIC_TERRITORY_NO

                assigned_count += 1

        log_info(f"M_21: Геометрический ВРИ по ЗПР присвоен {assigned_count} из {len(merging_indices)} контурам")
        return features_data

    def reassign_vri_by_geometry(
        self,
        features_data: List[Dict[str, Any]],
        zpr_layer: QgsVectorLayer
    ) -> List[Dict[str, Any]]:
        """Пересчёт План_ВРИ и Общая_земля для ВСЕХ контуров по геометрическому пересечению с ЗПР

        Используется в F_3_3 (Корректировка) когда пользователь мог изменить ЗПР
        или переместить контуры нарезки в другую зону ЗПР.

        Для каждого контура:
        1. Находит все контуры ЗПР, с которыми пересекается участок
        2. Выбирает ЗПР с максимальной площадью пересечения
        3. Присваивает План_ВРИ и Общая_земля из этого контура ЗПР

        Args:
            features_data: Список словарей с данными контуров
            zpr_layer: Слой ЗПР для геометрического определения

        Returns:
            Обновлённый список features_data с пересчитанными План_ВРИ и Общая_земля
        """
        if not features_data:
            return features_data

        if not zpr_layer or not zpr_layer.isValid():
            log_warning("M_21: Слой ЗПР не передан или невалиден для пересчёта ВРИ")
            return features_data

        # Загружаем базу ВРИ
        if not self._load_vri_database():
            log_error("M_21: Не удалось загрузить базу VRI.json для пересчёта ВРИ")
            return features_data

        # Ищем поле ВРИ в слое ЗПР
        vri_field = self._find_vri_field(zpr_layer)
        if not vri_field:
            log_warning(f"M_21: Поле VRI не найдено в слое ЗПР {zpr_layer.name()}")
            return features_data

        # Кэшируем данные ЗПР (геометрия, ID, ВРИ)
        zpr_cache: List[Dict] = []
        for zpr_feature in zpr_layer.getFeatures():
            zpr_geom = zpr_feature.geometry()
            if zpr_geom.isEmpty():
                continue

            zpr_id = zpr_feature['ID'] if 'ID' in zpr_feature.fields().names() else zpr_feature.id()
            vri_value = zpr_feature[vri_field]

            if not vri_value or str(vri_value).strip() in ('', '-', 'NULL', 'None'):
                continue

            vri_str = str(vri_value).strip()
            # Парсим множественные ВРИ
            vri_list = self._parse_multiple_vri(vri_str)

            vri_data_list = []
            for single_vri in vri_list:
                vri_data = self._get_vri_data_for_single(single_vri)
                if vri_data:
                    vri_data_list.append(vri_data)

            if vri_data_list:
                zpr_cache.append({
                    'id': int(zpr_id) if zpr_id else zpr_feature.id(),
                    'geometry': zpr_geom,
                    'vri_data_list': vri_data_list
                })

        if not zpr_cache:
            log_warning("M_21: Нет валидных ЗПР с ВРИ для пересчёта")
            return features_data

        assigned_count = 0
        skipped_count = 0

        # Для каждого контура находим ЗПР по геометрии
        for item in features_data:
            geom = item.get('geometry')

            if not geom or geom.isEmpty():
                skipped_count += 1
                continue

            # Находим ЗПР с максимальной площадью пересечения
            best_zpr = None
            best_intersection_area = 0.0

            for zpr in zpr_cache:
                intersection = geom.intersection(zpr['geometry'])
                if intersection.isEmpty():
                    continue

                intersection_area = intersection.area()
                if intersection_area > best_intersection_area:
                    best_intersection_area = intersection_area
                    best_zpr = zpr

            if best_zpr:
                vri_data_list = best_zpr['vri_data_list']
                attrs = item.get('attributes', {})

                # План_ВРИ - объединяем все full_name через ", "
                full_names = [vri.get('full_name', '') for vri in vri_data_list if vri.get('full_name')]
                attrs['План_ВРИ'] = ', '.join(full_names) if full_names else '-'

                # Общая_земля - если хотя бы один ВРИ относится к территории общего пользования
                is_public = any(vri.get('is_public_territory', False) for vri in vri_data_list)
                attrs['Общая_земля'] = self.PUBLIC_TERRITORY_YES if is_public else self.PUBLIC_TERRITORY_NO

                assigned_count += 1
            else:
                skipped_count += 1

        log_info(f"M_21: Пересчёт ВРИ по геометрии ЗПР: присвоено {assigned_count}, "
                f"пропущено {skipped_count} (нет пересечения с ЗПР)")
        return features_data
