# -*- coding: utf-8 -*-
"""
Msm_24_2 - Маппинг полей между слоями выписок и выборки

Определяет какие поля из выписок синхронизировать в слои выборки
и приоритет каждого поля.

Маппинг учитывает реальную структуру полей из Base_selection_ZU.json / Base_selection_OKS.json

Приоритетные поля (всегда заменяют):
    - Площадь (выписка точнее: 100 вместо 99.1)
    - Права, Собственники
    - Обременения, Арендаторы

Дополняющие поля (только если пусто):
    - Адрес, Категория, ВРИ

Перенесено из Fsm_2_2_2_field_mapper.py
"""

from typing import List, Tuple, Dict
from qgis.core import QgsVectorLayer

from Daman_QGIS.utils import log_info, log_warning


class Msm_24_2_FieldMapper:
    """Создание маппинга полей для синхронизации"""

    # Маппинг полей выписок -> слой выборки ЗУ (оба working_name)
    # Структура: {выборка_поле: (выписка_поле, priority)}
    #
    # После рефакторинга импорта (DATABASE-DRIVEN):
    # - Поля в выписках создаются с working_name из Base_field_mapping_EGRN.json
    # - Поля в выборке тоже используют working_name из Base_selection_ZU.json
    # - Названия полей ИДЕНТИЧНЫ (маппинг 1:1)
    # - Собственники/Арендаторы уже собраны в одно поле (conversion="semicolon_join")
    ZU_FIELD_MAPPINGS = {
        'КН': ('КН', 'skip'),  # Кадастровый номер - ключ, не меняем
        'Тип_объекта': ('Тип_объекта', 'fill'),  # Тип объекта (Землепользование, ЕЗ и т.д.)
        'Адрес_Местоположения': ('Адрес_Местоположения', 'fill'),  # Адрес
        'Категория': ('Категория', 'fill'),  # Категория земель
        'ВРИ': ('ВРИ', 'fill'),  # Вид разрешенного использования
        'Площадь': ('Площадь', 'replace'),  # Площадь - ПРИОРИТЕТ выписки!
        'Права': ('Права', 'replace'),  # Вид права
        'Обременения': ('Обременения', 'replace'),  # Тип обременения
        'Собственники': ('Собственники', 'replace'),  # Правообладатель (уже собраны все типы)
        'Арендаторы': ('Арендаторы', 'replace'),  # Лицо в пользу которого установлено обременение
        'Статус': ('Статус', 'fill'),  # Статус объекта
    }

    # Маппинг полей выписок -> слой выборки ОКС (оба working_name)
    # Структура: {выборка_поле: (выписка_поле, priority)}
    #
    # Примечание: В выборке ОКС НЕТ полей Права/Обременения/Собственники/Арендаторы
    # (хотя они есть в выписках build_record)
    OKS_FIELD_MAPPINGS = {
        'КН': ('КН', 'skip'),  # Кадастровый номер - ключ
        'Тип_ОКСа': ('Тип_ОКСа', 'fill'),  # Тип ОКС (Здание, Сооружение и т.д.)
        'Адрес_Местоположения': ('Адрес_Местоположения', 'fill'),  # Адрес
        'Наименование': ('Наименование', 'fill'),  # Наименование ОКС
        'Назначение': ('Назначение', 'fill'),  # Назначение (Жилое и т.д.)
        'Значение': ('Значение', 'replace'),  # Площадь ОКС - ПРИОРИТЕТ выписки!
        'Статус': ('Статус', 'fill'),  # Статус объекта
        'Связанные_ЗУ': ('Связанные_ЗУ', 'fill'),  # КН ЗУ, на которых расположен ОКС
        # НЕ синхронизируем: 'Характеристика' (вычисляемое поле, "-" в xml_xpath)
    }

    def __init__(self):
        """Инициализация"""
        pass

    def create_field_mappings(
        self,
        layer_pairs: List[Tuple[QgsVectorLayer, QgsVectorLayer]]
    ) -> Dict[str, List[Tuple[str, str, str]]]:
        """
        Создать маппинг полей для каждой пары слоёв

        Args:
            layer_pairs: Список пар (vypiska_layer, selection_layer)

        Returns:
            Dict[pair_id, [(vypiska_field_ru, selection_field_ru, priority)]]:
                pair_id = f"{vypiska_name}->{selection_name}"
                vypiska_field_ru: Русское название поля в выписке (working_name)
                selection_field_ru: Русское название поля в выборке (working_name)
                priority = "replace" | "fill" | "skip"
        """
        mappings = {}

        for vypiska_layer, selection_layer in layer_pairs:
            pair_id = f"{vypiska_layer.name()}->{selection_layer.name()}"

            # Определяем какой маппинг использовать
            # Слой ЗУ: Le_2_1_1_1_Выборка_ЗУ
            # Слой ОКС: L_2_1_2_Выборка_ОКС
            layer_name = selection_layer.name()
            if 'Выборка_ЗУ' in layer_name or 'Le_2_1_1_1' in layer_name:
                field_map = self.ZU_FIELD_MAPPINGS
                log_info(f"Msm_24_2: [{pair_id}] Используется маппинг для ЗУ")
            elif 'Выборка_ОКС' in layer_name or 'L_2_1_2' in layer_name:
                field_map = self.OKS_FIELD_MAPPINGS
                log_info(f"Msm_24_2: [{pair_id}] Используется маппинг для ОКС")
            else:
                log_warning(f"Msm_24_2: [{pair_id}] Неизвестный тип слоя выборки, пропускаем")
                continue

            # Получаем доступные поля
            vypiska_fields = {f.name() for f in vypiska_layer.fields()}
            selection_fields = {f.name() for f in selection_layer.fields()}

            pair_mappings = []

            # Проходим по всем полям из маппинга
            for selection_field_ru, (vypiska_field_ru, priority) in field_map.items():
                # Проверяем что поле есть в слое выборки
                if selection_field_ru not in selection_fields:
                    log_warning(
                        f"Msm_24_2: [{pair_id}] Поле '{selection_field_ru}' отсутствует в слое выборки"
                    )
                    continue

                # Пропускаем служебные поля (КН - ключ синхронизации)
                if priority == 'skip':
                    continue

                # Проверяем что поле есть в слое выписок
                if vypiska_field_ru in vypiska_fields:
                    pair_mappings.append((vypiska_field_ru, selection_field_ru, priority))
                else:
                    log_warning(
                        f"Msm_24_2: [{pair_id}] Поле '{vypiska_field_ru}' отсутствует в слое выписок"
                    )

            if pair_mappings:
                mappings[pair_id] = pair_mappings
                replace_count = sum(1 for _, _, p in pair_mappings if p == 'replace')
                fill_count = sum(1 for _, _, p in pair_mappings if p == 'fill')
                log_info(
                    f"Msm_24_2: [{pair_id}] Создан маппинг: {len(pair_mappings)} полей "
                    f"({replace_count} замен, {fill_count} дополнений)"
                )
            else:
                log_warning(f"Msm_24_2: [{pair_id}] Нет доступных полей для синхронизации")

        return mappings
