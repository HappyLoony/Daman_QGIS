# -*- coding: utf-8 -*-
"""Менеджер справочных данных градостроительных объектов"""

from typing import List, Dict, Optional
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
from Daman_QGIS.utils import normalize_for_classification


class UrbanPlanningReferenceManager(BaseReferenceLoader):
    """Менеджер для работы со справочниками градостроительных объектов"""

    OFFSET_REDLINE_FILE = 'Offset_redline.json'
    OTHER_FILE = 'Other.json'
    PUBLIC_EASEMENT_FILE = 'Public_easement.json'
    REDLINE_FILE = 'Redline.json'
    FUN_ZONES_DISTRIBUTION_FILE = 'Base_fun_zones_distribution.json'
    TERR_ZONES_DISTRIBUTION_FILE = 'Base_terr_zones_distribution.json'

    # Методы для работы с отступами от красных линий
    def get_offset_redline(self) -> List[Dict]:
        """
        Получить отступы от красных линий

        Returns:
            Список отступов от красных линий
        """
        return self._load_json(self.OFFSET_REDLINE_FILE) or []

    # Методы для работы с прочими объектами
    def get_other_objects(self) -> List[Dict]:
        """
        Получить прочие объекты

        Returns:
            Список прочих объектов градостроительства
        """
        return self._load_json(self.OTHER_FILE) or []

    def get_other_object_by_code(self, code: str) -> Optional[Dict]:
        """
        Получить прочий объект по коду

        Args:
            code: Код объекта (ищется в полях 'code' и 'code_code')

        Returns:
            Словарь с данными объекта или None
        """
        # Проверяем индексы для обоих полей
        index_key_code = 'other_by_code'
        index_key_code_code = 'other_by_code_code'

        if index_key_code not in self._index_cache:
            objects = self.get_other_objects()
            self._index_cache[index_key_code] = self._build_index(objects, 'code')
            self._index_cache[index_key_code_code] = self._build_index(objects, 'code_code')

        # Ищем сначала по code, затем по code_code
        result = self._index_cache[index_key_code].get(code)
        if result:
            return result
        return self._index_cache[index_key_code_code].get(code)

    # Методы для работы с публичными сервитутами
    def get_public_easements(self) -> List[Dict]:
        """
        Получить список публичных сервитутов

        Returns:
            Список публичных сервитутов
        """
        return self._load_json(self.PUBLIC_EASEMENT_FILE) or []

    def get_public_easement_by_type(self, easement_type: str) -> Optional[Dict]:
        """
        Получить публичный сервитут по типу

        Args:
            easement_type: Тип публичного сервитута

        Returns:
            Словарь с данными сервитута или None
        """
        return self._get_by_key(
            data_getter=self.get_public_easements,
            index_key='easement_by_type',
            field_name='type',
            value=easement_type
        )

    # Методы для работы с красными линиями
    def get_redlines(self) -> List[Dict]:
        """
        Получить список красных линий

        Returns:
            Список красных линий
        """
        return self._load_json(self.REDLINE_FILE) or []

    def get_redline_by_status(self, status: str) -> Optional[Dict]:
        """
        Получить красную линию по статусу

        Args:
            status: Статус красной линии

        Returns:
            Словарь с данными красной линии или None
        """
        return self._get_by_key(
            data_getter=self.get_redlines,
            index_key='redline_by_status',
            field_name='status',
            value=status
        )

    # Методы для работы с распределением функциональных зон (Fsm_1_2_18)
    def get_fun_zones_mapping(self) -> List[Dict]:
        """
        Получить правила распределения функциональных зон.

        Формат записи:
            {
                "classname": "<название зоны из WFS Le_1_2_8_1>",
                "status": "<значение поля status из WFS>",
                "layer_name": "<имя слоя назначения Le_1_2_8_*_Фун_зоны_*_сущ/_план>"
            }

        Returns:
            Список правил распределения (classname + status -> layer_name)
        """
        return self._load_json(self.FUN_ZONES_DISTRIBUTION_FILE) or []

    def get_fun_zone_layer(self, classname: str, status: str) -> Optional[str]:
        """
        Найти слой назначения для функциональной зоны по паре (classname, status).

        Сравнение через normalize_for_classification: устраняет ложные negative
        из-за невидимых символов в строках WFS NSPD (nbsp вместо пробела и т.п.).

        Args:
            classname: Название зоны (из поля classname в WFS)
            status: Статус (из поля status в WFS)

        Returns:
            Имя слоя назначения или None если пара не найдена в маппинге
        """
        n_classname = normalize_for_classification(classname)
        n_status = normalize_for_classification(status)
        for rule in self.get_fun_zones_mapping():
            if (normalize_for_classification(rule.get('classname')) == n_classname
                    and normalize_for_classification(rule.get('status')) == n_status):
                return rule.get('layer_name')
        return None

    # Методы для работы с распределением территориальных зон (Fsm_1_2_17)
    def get_terr_zones_mapping(self) -> List[Dict]:
        """
        Получить правила распределения территориальных зон.

        Формат записи:
            {
                "classname": "<название зоны из WFS Le_1_2_9_1>",
                "layer_name": "<имя слоя назначения Le_1_2_9_*_Тер_зоны_*>"
            }

        Territrial zones не разделяются по status (семантика данных WFS).

        Returns:
            Список правил распределения (classname -> layer_name)
        """
        return self._load_json(self.TERR_ZONES_DISTRIBUTION_FILE) or []

    def get_terr_zone_layer(self, classname: str) -> Optional[str]:
        """
        Найти слой назначения для территориальной зоны по classname.

        Линейный поиск без кэш-индекса: у территориальных зон ~5 записей,
        а shared-кэш может быть загрязнён пустыми данными при race condition
        (первый вызов до готовности API запомнил бы пустой индекс навсегда).

        Сравнение через normalize_for_classification: устраняет ложные negative
        из-за невидимых символов в строках WFS NSPD (nbsp вместо пробела и т.п.).

        Args:
            classname: Название зоны (из поля classname в WFS)

        Returns:
            Имя слоя назначения или None если classname не найден в маппинге
        """
        n_classname = normalize_for_classification(classname)
        for rule in self.get_terr_zones_mapping():
            if normalize_for_classification(rule.get('classname')) == n_classname:
                return rule.get('layer_name')
        return None
